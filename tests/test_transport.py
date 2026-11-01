import unittest
from unittest.mock import patch
from pair_aki.transport import JsonModelClient,local_url
from pair_aki.backend.domain import ContractError
from pair_aki.backend.tool_contracts import ModelResponseError


class TransportTests(unittest.TestCase):
    def test_nonlocal_and_embedded_credentials_rejected(self):
        for url in ('http://example.com/v1','http://token@127.0.0.1:8000/v1','https://127.0.0.1:8000/v1'):
            with self.assertRaises(ContractError):local_url(url)
    @patch('pair_aki.transport.request_json')
    def test_wrong_model_never_admitted(self,call):
        call.return_value={'model':'other','choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with self.assertRaises(ModelResponseError):JsonModelClient('http://127.0.0.1:8000/v1','expected').complete('s',{}, {},timeout=1)
    @patch('pair_aki.transport.request_json')
    def test_summary_preserves_every_statement(self,call):
        call.return_value={'model':'expected','choices':[{'finish_reason':'stop','message':{'content':'{"ordered_ids":["b","a"]}'}}]}
        client=JsonModelClient('http://127.0.0.1:8000/v1','expected')
        statements=[{'id':'a','text':'verified 1'},{'id':'b','text':'verified 2'}]
        rows,_=client.select_statements(statements,timeout=1)
        self.assertEqual(rows,[statements[1],statements[0]])
        call.return_value['choices'][0]['message']['content']='{"ordered_ids":["a","a"]}'
        with self.assertRaises(ModelResponseError):client.select_statements(statements,timeout=1)
