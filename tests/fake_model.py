"""Protocol-only HTTP fixture for AGH smoke tests. It is not an AI model."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import argparse


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'))
        value=json.loads(self.rfile.read(n));schema=value['response_format']['json_schema']['schema']
        props=schema.get('properties',{})
        if 'outcomes' in props:
            output={'outcomes':['event_prediction','comparable_cases'],'clarification':None}
        elif 'anyOf' in schema:
            output={'reason':'Explicit test-only plan','state_binding':'latest_accepted_same_case_and_time',
                    'actions':['predict_event_24h','retrieve_comparable_cases','finish'],
                    'question':None,'clarification_kind':None}
        elif 'ordered_ids' in props:
            output={'ordered_ids':props['ordered_ids']['items']['enum']}
        elif 'tool' in props:
            output={'tool':props['tool']['enum'][0],'reason':'Explicit test-only stage'}
        else:raise ValueError('Unsupported fixture schema')
        raw=json.dumps({'model':value['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}],
                        'usage':{'prompt_tokens':0,'completion_tokens':0}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);a=p.parse_args()
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
