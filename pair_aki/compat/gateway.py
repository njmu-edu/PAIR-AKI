"""Loopback API v2 gateway. No assessment bypasses the pinned AGH child runtime."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import signal
import threading
import time
from urllib.parse import urlsplit, unquote, quote
from pair_aki.server import handler_for as base_handler
from pair_aki.autonomous.ledger import Ledger
from .bridge import Client, validate_request, validate_capabilities

PIN = '4bc36bc4c4441206388a53bece17379c1d7be14d'


class Application:
    def __init__(self, state, node, runner, api_url, llm_url):
        self.store = Ledger(state)
        self.lease = (self.store.root / 'service.lock').open('a')
        fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.store.recover_interrupted()
        self.node, self.runner = str(Path(node).resolve()), str(Path(runner).resolve())
        self.api_url, self.llm_url = api_url, llm_url
        self.client = Client(api_url)
        self.capabilities()  # Fail startup if the current trained application is unavailable.
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.slots = threading.BoundedSemaphore(4)

    def capabilities(self):
        caps = self.client.call('/capabilities')
        validate_capabilities(caps)
        return {**caps, 'execution_runtime': {'name': 'Agnes Harness', 'upstream_commit': PIN,
                    'adapter': 'pedaki-current-v2', 'required_stages': 3}}

    def submit(self, request):
        validate_request(request)
        if not self.slots.acquire(blocking=False):
            raise ValueError('run_queue_full')
        try:
            rid = self.store.create(request)
            self.pool.submit(self.run, rid, request)
            return rid
        except Exception:
            self.slots.release()
            raise

    def run(self, rid, request):
        started = time.monotonic()
        self.store.start(rid)
        folder = self.store.root / 'agh' / rid
        folder.mkdir(parents=True, mode=0o700)
        request_file = folder / 'request.json'
        request_file.write_text(json.dumps(request, ensure_ascii=False))
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
               'PAIR_AKI_PROJECT_ROOT': str(Path(__file__).resolve().parents[2]),
               'PAIR_AKI_REQUEST': str(request_file), 'PAIR_AKI_STATE_ROOT': str(folder),
               'PAIR_AKI_API_URL': self.api_url, 'PAIR_AKI_MODEL_URL': self.llm_url,
               'PAIR_AKI_PYTHON': os.sys.executable}
        # Never inherit the historical preflight switch into a user request.
        env.pop('PAIR_AKI_PREFLIGHT', None)
        try:
            self.store.event(rid, {'kind': 'runtime', 'status': 'running', 'details': {'name': 'Agnes Harness', 'pin': PIN}})
            with (folder / 'stdout.log').open('x') as out, (folder / 'stderr.log').open('x') as err:
                child = subprocess.Popen([self.node, self.runner], env=env, stdout=out, stderr=err, start_new_session=True)
                try:
                    child.wait(timeout=430)
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
            receipts = list(folder.glob('*/run-receipt.json'))
            if child.returncode or len(receipts) != 1:
                raise ValueError('agh_execution_failed')
            receipt = json.loads(receipts[0].read_text())
            if not receipt['completed'] or receipt['step_tools'] != ['admit_case', 'execute_assessment', 'verify_assessment']:
                raise ValueError('agh_incomplete')
            record = json.loads((receipts[0].parent / 'verified-result.json').read_text())
            result = record['result']
            runtime = {'name': 'Agnes Harness', 'upstream_commit': PIN, 'session_id': receipt['run_id'],
                       'inner_run_id': record['run_id'], 'ledger_sha256': receipt['ledger_sha256'],
                       'stages': receipt['step_tools'], 'coordinator_calls': receipt['model_calls'],
                       'elapsed_seconds': round(time.monotonic() - started, 4)}
            for event in record['events']:
                self.store.event(rid, {k: v for k, v in event.items() if k not in {'seq', 'at'}})
            self.store.event(rid, {'kind': 'runtime_verified', 'status': 'complete', 'details': runtime})
            if result is not None:
                result['execution_runtime'] = runtime
                result['metrics']['inner_elapsed_seconds'] = result['metrics']['elapsed_seconds']
                result['metrics']['elapsed_seconds'] = runtime['elapsed_seconds']
                result['metrics']['inner_coordinator_calls'] = result['metrics']['coordinator_calls']
                result['metrics']['coordinator_calls'] += runtime['coordinator_calls']
            self.store.finish(rid, record['status'], result)
        except Exception as exc:
            self.store.event(rid, {'kind': 'runtime_failure', 'status': 'failed', 'reason': type(exc).__name__})
            self.store.finish(rid, 'failed', None)
        finally:
            self.slots.release()

    def close(self):
        self.pool.shutdown(wait=True)
        self.lease.close()


def handler_for(app):
    class Handler(base_handler(app)):
        def do_GET(self):
            if not self.guard():
                return self.error(403, 'host_not_allowed')
            path = urlsplit(self.path).path
            prefix = '/api/competition/v2'
            try:
                if path == prefix + '/capabilities':
                    return self.send(200, app.capabilities())
                if path == prefix + '/cases':
                    return self.send(200, app.client.call('/cases'))
                if path.startswith(prefix + '/cases/'):
                    return self.send(200, app.client.call('/cases/' + quote(unquote(path.rsplit('/', 1)[-1]), safe='')))
                if path.startswith(prefix + '/runs/'):
                    return self.send(200, app.store.read(path.rsplit('/', 1)[-1]))
                return self.error(404, 'route_not_found')
            except Exception:
                return self.error(404, 'resource_not_found')

        def do_POST(self):
            if not self.guard():
                return self.error(403, 'host_not_allowed')
            origin = self.headers.get('Origin')
            if origin and (urlsplit(origin).scheme != 'http' or urlsplit(origin).netloc != self.headers.get('Host')):
                return self.error(403, 'origin_not_allowed')
            if self.path != '/api/competition/v2/runs':
                return self.error(404, 'route_not_found')
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if not 0 < n <= 8192 or self.headers.get('Transfer-Encoding'):
                    return self.error(413, 'request_size')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.error(415, 'json_required')
                return self.send(202, {'run_id': app.submit(json.loads(self.rfile.read(n)))})
            except Exception:
                return self.error(400, 'invalid_request')
    return Handler


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('state', 'node', 'runner', 'api-url', 'llm-url'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--port', type=int, default=30888)
    args = parser.parse_args()
    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    app = Application(args.state, args.node, args.runner, args.api_url, args.llm_url)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app))
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
