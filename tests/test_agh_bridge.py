import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pair_aki.compat.bridge import execute,verify_record,validate_capabilities
from pair_aki.backend.domain import ContractError

REQUEST={'goal':'combined','case_ref':'ae-201','snapshot_ref':'snapshot-01','mode':'autonomous'}
CAPS={'api_version':'competition-v2','coordinator':{'mode':'live'},
      'medical_models':{'M_P':{'mode':'synthetic','model_id':'fixture-p','bundle_sha256':None},
                        'M_R':{'mode':'synthetic','model_id':'fixture-r','bundle_sha256':None}},
      'source':{'sha256':'source-01'}}
SNAPSHOT={'case_ref':'ae-201','snapshot_ref':'snapshot-01','patient_ref':'fixture-patient',
          'decision_time':'2026-01-01T00:00:00Z','source_kind':'synthetic'}


class FakeClient:
    def __init__(self):self.submissions=0
    def call(self,path,body=None):
        if path=='/capabilities':return copy.deepcopy(CAPS)
        if path.startswith('/cases/'):return copy.deepcopy(SNAPSHOT)
        if path=='/runs':self.submissions+=1;return {'run_id':'run-'+'a'*32}
        return {'run_id':'run-'+'a'*32,'status':'succeeded','request':REQUEST,
                'result':{'final_snapshot':SNAPSHOT,'versions':{'source_sha256':'source-01'},
                          'narrative':[],'evidence':[],'prediction':None,'comparables':None}}


class BridgeTests(unittest.TestCase):
    @patch.dict(os.environ,{'PAIR_AKI_ALLOW_SYNTHETIC':'1'})
    def test_three_bound_stages(self):
        client=FakeClient();prior={}
        with tempfile.TemporaryDirectory() as folder:
            for name in ('admit_case','execute_assessment','verify_assessment'):
                prior[name]=execute(name,REQUEST,prior,client,Path(folder))
            self.assertEqual(client.submissions,1)
            self.assertEqual(prior['verify_assessment']['output']['application_status'],'succeeded')
            self.assertTrue((Path(folder)/'verified-result.json').exists())
    def test_no_skipping(self):
        client=FakeClient()
        with self.assertRaises(ContractError):execute('execute_assessment',REQUEST,{},client,Path('/unused'))
        self.assertEqual(client.submissions,0)
    @patch.dict(os.environ,{'PAIR_AKI_ALLOW_SYNTHETIC':'1'})
    def test_unknown_post_cannot_repeat(self):
        client=FakeClient();prior={'admit_case':execute('admit_case',REQUEST,{},client,Path('/unused'))}
        with tempfile.TemporaryDirectory() as folder:
            execute('execute_assessment',REQUEST,prior,client,Path(folder))
            with self.assertRaises(FileExistsError):execute('execute_assessment',REQUEST,prior,client,Path(folder))
        self.assertEqual(client.submissions,1)
    @patch.dict(os.environ,{},clear=True)
    def test_synthetic_opt_in_required(self):
        with self.assertRaises(ContractError):validate_capabilities(CAPS)
    def test_case_identity_checked(self):
        record=FakeClient().call('/runs/x');record['result']['final_snapshot']={**SNAPSHOT,'patient_ref':'other'}
        with self.assertRaises(ContractError):verify_record(record,REQUEST,{**SNAPSHOT,'capabilities':CAPS})
