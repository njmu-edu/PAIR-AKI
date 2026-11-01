import json
from pathlib import Path
import tempfile
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import unittest
from pair_aki.server import Application,handler_for
from pair_aki.demo import DemoCoordinator
from pair_aki.specialists.providers import SyntheticPredictor,SyntheticComparator
from pair_aki.autonomous.repository import SyntheticRepository


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name,DemoCoordinator(),SyntheticPredictor(SyntheticRepository().labels),SyntheticComparator())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
    def close(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.thread.join()
    def call(self,path,body=None,extra=None):
        con=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            con.request('GET' if body is None else 'POST','/api/competition/v2'+path,
                        body=None if body is None else json.dumps(body),
                        headers={'Content-Type':'application/json',**(extra or {})})
            r=con.getresponse();return r.status,json.loads(r.read())
        finally:con.close()
    def test_complete_task_and_binary_contract(self):
        _,rows=self.call('/cases');q=rows['cases'][0]
        code,start=self.call('/runs',{'goal':'Combined assessment','case_ref':q['case_ref'],'snapshot_ref':q['snapshot_ref'],'mode':'autonomous'})
        self.assertEqual(code,202)
        for _ in range(200):
            _,run=self.call('/runs/'+start['run_id'])
            if run['status'] not in {'queued','running'}:break
            time.sleep(.01)
        self.assertEqual(run['status'],'succeeded')
        self.assertIs(type(run['result']['prediction']['label']),int)
        self.assertEqual(run['result']['prediction']['receipt']['mode'],'synthetic')
        self.assertLessEqual(len(run['result']['comparables']['matches']),3)
    def test_cross_origin_rejected(self):
        code,_=self.call('/runs',{}, {'Origin':'http://other.invalid'})
        self.assertEqual(code,403)
    def test_private_case_cannot_be_uploaded(self):
        code,_=self.call('/runs',{'goal':'predict','case_ref':'unregistered','snapshot_ref':'made-up','mode':'autonomous'})
        self.assertEqual(code,400)
    def test_demo_identity_is_explicit(self):
        _,caps=self.call('/capabilities')
        self.assertEqual(caps['coordinator']['mode'],'scripted_test')
        self.assertEqual(caps['source']['version'],'autonomous-fixtures-v1')
        self.assertEqual(caps['medical_models']['M_P']['mode'],'synthetic')
