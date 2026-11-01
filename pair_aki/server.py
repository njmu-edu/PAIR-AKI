"""Portable loopback API v2 and optional static frontend, synthetic inputs only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import signal
import threading
from urllib.parse import urlsplit, unquote
from pair_aki.autonomous.engine import Engine
from pair_aki.autonomous.ledger import Ledger, TERMINAL
from pair_aki.autonomous.recall import ReferenceIndex
from pair_aki.autonomous.repository import SyntheticRepository
from pair_aki.autonomous.state import Budget, factual_view
from pair_aki.backend.domain import ContractError
from pair_aki.specialists.providers import SyntheticPredictor, SyntheticComparator

PREFIX = '/api/competition/v2'


class Application:
    def __init__(self, state_dir, coordinator, predictor, comparator, *, budget=Budget()):
        self.repository = SyntheticRepository()
        self.predictor, self.comparator, self.coordinator = predictor, comparator, coordinator
        self.store = Ledger(state_dir)
        self.lease = (self.store.root/'service.lock').open('a')
        fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.store.recover_interrupted()
        self.engine = Engine(self.repository, ReferenceIndex(self.repository.references),
                             predictor, comparator, self.store, coordinator, budget)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.slots = threading.BoundedSemaphore(4)

    def submit(self, request):
        self.engine.validate_request(request)
        if not self.slots.acquire(blocking=False):
            raise ContractError('run_queue_full')
        try:
            rid = self.store.create(request)
            self.pool.submit(self._run, rid, request)
            return rid
        except Exception:
            self.slots.release()
            raise

    def _run(self, rid, request):
        try:
            self.engine.execute(rid, request)
        except Exception as exc:
            state = self.store.read(rid)
            if state['status'] == 'queued': self.store.start(rid)
            if state['status'] not in TERMINAL:
                self.store.event(rid, {'kind':'run_failure', 'status':'failed', 'reason':type(exc).__name__})
                self.store.finish(rid, 'failed', None)
        finally:
            self.slots.release()

    def capabilities(self):
        return {'api_version':'competition-v2', 'agent_version':self.engine.version,
                'coordinator':{'mode':self.coordinator.mode, 'model_id':self.coordinator.model_id},
                'medical_models':{role:{'mode':p.mode, 'model_id':p.model_id, 'bundle_sha256':getattr(p,'bundle_sha256',None)} for role,p in
                                  (('M_P',self.predictor),('M_R',self.comparator))},
                'budget':asdict(self.engine.budget),
                'source':{'version':self.repository.version, 'sha256':self.repository.identity}}

    def close(self):
        self.pool.shutdown(wait=True)
        self.lease.close()


def handler_for(app, static=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def send(self, status, data, content_type='application/json'):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def error(self, status, reason):
            return self.send(status, {'error':{'code':reason,'message':reason}})
        def guard(self):
            host=self.headers.get('Host','')
            try:parsed=urlsplit('http://'+host)
            except ValueError:return False
            return parsed.hostname in {'127.0.0.1','localhost','::1'} and not parsed.username
        def do_GET(self):
            if not self.guard():return self.error(403,'host_not_allowed')
            path=urlsplit(self.path).path
            try:
                if path==PREFIX+'/capabilities':return self.send(200,app.capabilities())
                if path==PREFIX+'/cases':return self.send(200,{'cases':app.repository.list_cases()})
                if path.startswith(PREFIX+'/cases/'):
                    return self.send(200,factual_view(app.repository.get(unquote(path.rsplit('/',1)[-1]))))
                if path.startswith(PREFIX+'/runs/'):return self.send(200,app.store.read(path.rsplit('/',1)[-1]))
                if static and not path.startswith('/api/'):
                    target=(static/unquote(path).lstrip('/')).resolve()
                    if not target.is_relative_to(static):return self.error(403,'path_not_allowed')
                    if target.is_dir():target=target/'index.html'
                    if target.is_file():return self.send(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
                return self.error(404,'route_not_found')
            except (ContractError, KeyError, ValueError):return self.error(404,'resource_not_found')
        do_HEAD=do_GET
        def do_POST(self):
            if not self.guard():return self.error(403,'host_not_allowed')
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers.get('Host',''):return self.error(403,'origin_not_allowed')
            if self.path!=PREFIX+'/runs':return self.error(404,'route_not_found')
            try:
                n=int(self.headers.get('Content-Length','0'))
                if self.headers.get('Transfer-Encoding') or not 0<n<=8192:return self.error(413,'request_size')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.error(415,'json_required')
                return self.send(202,{'run_id':app.submit(json.loads(self.rfile.read(n)))})
            except (ContractError, ValueError, KeyError, TypeError) as exc:
                return self.error(429 if str(exc)=='run_queue_full' else 400,'request_rejected')
    return Handler


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir',required=True)
    p.add_argument('--port',type=int,default=30886)
    p.add_argument('--static',type=Path)
    p.add_argument('--scripted-demo',action='store_true')
    p.add_argument('--synthetic-medical',action='store_true')
    a=p.parse_args();os.umask(0o077)
    if a.scripted_demo:
        from pair_aki.demo import DemoCoordinator
        coordinator=DemoCoordinator()
    else:
        from pair_aki.autonomous.coordinator import LiveCoordinator
        from pair_aki.transport import JsonModelClient
        coordinator=LiveCoordinator(JsonModelClient(os.environ['PAIR_AKI_MODEL_URL'],os.environ['PAIR_AKI_MODEL']))
    if a.synthetic_medical:
        predictor,comparator=SyntheticPredictor(SyntheticRepository().labels),SyntheticComparator()
    else:
        from pair_aki.medical_provider import MedicalEndpoint
        predictor=MedicalEndpoint(os.environ['PAIR_AKI_PREDICTOR_URL'],'M_P')
        comparator=MedicalEndpoint(os.environ['PAIR_AKI_RERANKER_URL'],'M_R')
    app=Application(a.state_dir,coordinator,predictor,comparator)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),handler_for(app,a.static.resolve() if a.static else None))
    server.daemon_threads=True
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    print(json.dumps({'ready':True,**app.capabilities()}),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
