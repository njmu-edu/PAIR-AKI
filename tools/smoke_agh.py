"""Bounded AGH smoke using an explicitly fake chat endpoint and synthetic medical tools."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from pair_aki.transport import request_json


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--node',required=True);p.add_argument('--runner',required=True);a=p.parse_args()
    base=Path(__file__).resolve().parents[1]
    model_port,inner_port,outer_port=free_port(),free_port(),free_port()
    with tempfile.TemporaryDirectory(prefix='pair-aki-agh-') as state:
        root=Path(state);processes=[];logs=[]
        env={**os.environ,'PAIR_AKI_MODEL_URL':f'http://127.0.0.1:{model_port}/v1',
             'PAIR_AKI_MODEL':'explicit-test-fixture','PAIR_AKI_ALLOW_SYNTHETIC':'1','PYTHONDONTWRITEBYTECODE':'1'}
        commands=[
            [sys.executable,'-B','tests/fake_model.py','--port',str(model_port)],
            [sys.executable,'-B','-m','pair_aki.server','--state-dir',str(root/'inner'),'--port',str(inner_port),'--synthetic-medical'],
            [sys.executable,'-B','-m','pair_aki.compat.gateway','--state',str(root/'outer'),'--node',a.node,'--runner',a.runner,
             '--api-url',f'http://127.0.0.1:{inner_port}','--llm-url',env['PAIR_AKI_MODEL_URL'],'--port',str(outer_port)]]
        try:
            for i,command in enumerate(commands):
                log=(root/f'process-{i}.txt').open('w');logs.append(log)
                processes.append(subprocess.Popen(command,cwd=base,env=env,stdout=log,stderr=log))
                if i < 2:
                    port = model_port if i == 0 else inner_port
                    ready_deadline = time.monotonic() + 15
                    while time.monotonic() < ready_deadline:
                        try:
                            with socket.create_connection(('127.0.0.1', port), timeout=.5):
                                break
                        except OSError:
                            if processes[-1].poll() is not None:
                                raise RuntimeError('dependency_exited_before_ready')
                            time.sleep(.1)
                    else:
                        raise TimeoutError('dependency_not_ready')
            api=f'http://127.0.0.1:{outer_port}/api/competition/v2'
            ready=time.monotonic()+25
            while time.monotonic()<ready:
                try:request_json(api+'/capabilities',timeout=1);break
                except Exception:
                    if any(proc.poll() is not None for proc in processes):raise RuntimeError('smoke_process_exited')
                    time.sleep(.1)
            else:raise TimeoutError('smoke_startup')
            case=request_json(api+'/cases')['cases'][0]
            rid=request_json(api+'/runs',{'case_ref':case['case_ref'],'snapshot_ref':case['snapshot_ref'],
                             'goal':'Combined assessment','mode':'autonomous'})['run_id']
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                record=request_json(api+'/runs/'+rid)
                if record['status'] not in {'queued','running'}:break
                time.sleep(.1)
            if record['status']!='succeeded':raise RuntimeError('smoke_run_failed:'+record['status'])
            files=list((root/'outer'/'agh'/rid).glob('*/kernel-ledger.json'))
            assert len(files)==1
            ledger=json.loads(files[0].read_text())
            calls=[x for x in ledger if x['type']=='tool/call'];results=[x for x in ledger if x['type']=='tool/result']
            assert [x['data']['name'] for x in calls]==['admit_case','execute_assessment','verify_assessment']
            assert len(results)==3 and not any(x['data']['isError'] for x in results)
            print(json.dumps({'status':'passed','agh_native_tool_calls':3,'agh_native_tool_results':3,
                              'model_kind':'explicit-test-fixture','medical_mode':'synthetic',
                              'clinical_or_live_model_claim':False}))
        except Exception:
            for log in logs:log.flush()
            for path in root.glob('process-*.txt'):print(path.name+': '+path.read_text()[-2500:],file=sys.stderr)
            for pattern in ('outer/agh/*/*/failure.json','outer/agh/*/stderr.log','outer/agh/*/stdout.log'):
                for path in root.glob(pattern):print(path.name+': '+path.read_text()[-2500:],file=sys.stderr)
            raise
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
            for log in logs:log.close()


if __name__=='__main__':main()
