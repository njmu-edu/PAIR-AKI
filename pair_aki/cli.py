"""Read the synthetic case list or run a bounded task through the selected loopback API."""
import argparse
import json
import time
from pair_aki.transport import request_json, local_url
from pair_aki.autonomous.ledger import TERMINAL


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api',default='http://127.0.0.1:30886')
    p.add_argument('--list',action='store_true')
    p.add_argument('--case',default='ae-201')
    p.add_argument('--goal',default='Combined assessment: predict the 24-hour event and retrieve comparable cases.')
    a=p.parse_args();base=local_url(a.api)+'/api/competition/v2'
    if a.list:
        print(json.dumps(request_json(base+'/cases'),ensure_ascii=False,indent=2));return
    snapshot=request_json(base+'/cases/'+a.case)
    run=request_json(base+'/runs',{'goal':a.goal,'case_ref':a.case,'snapshot_ref':snapshot['snapshot_ref'],'mode':'autonomous'})
    rid=run['run_id'];print('run_id='+rid,flush=True);deadline=time.monotonic()+450
    while time.monotonic()<deadline:
        record=request_json(base+'/runs/'+rid)
        if record['status'] in TERMINAL:
            print(json.dumps(record,ensure_ascii=False,indent=2));return
        time.sleep(.5)
    raise TimeoutError('Task remains readable by its original run ID.')


if __name__=='__main__':main()
