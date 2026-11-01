"""Three real application stages for the pinned AGH runtime, using loopback API v2."""
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from pair_aki.backend.domain import ContractError, digest
from pair_aki.backend.narrative import verify_references
from pair_aki.autonomous.state import require_no_model_scores

TOOLS = ('admit_case', 'execute_assessment', 'verify_assessment')
TERMINAL = {'succeeded', 'partial', 'failed', 'blocked', 'needs_clarification'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ContractError('redirect_forbidden')


class Client:
    def __init__(self, url):
        if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', url):
            raise ContractError('loopback_api_required')
        self.url = url + '/api/competition/v2'
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=15) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ContractError('api_response_budget')
        return json.loads(raw)


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {'goal', 'case_ref', 'snapshot_ref', 'mode'}:
        raise ContractError('request_schema')
    if not isinstance(value['goal'], str) or not 1 <= len(value['goal'].strip()) <= 4000:
        raise ContractError('goal_schema')
    if value['mode'] not in {'autonomous', 'general', 'fixed'}:
        raise ContractError('mode_schema')
    for field in ('case_ref', 'snapshot_ref'):
        if not isinstance(value[field], str) or not re.fullmatch(r'[\w:.-]{1,200}', value[field]):
            raise ContractError('reference_schema')
    return value


def validate_capabilities(caps):
    if caps['api_version'] != 'competition-v2' or caps['coordinator']['mode'] != 'live':
        raise ContractError('live_coordinator_required_for_agh')
    for role in ('M_P', 'M_R'):
        model = caps['medical_models'][role]
        if model['mode'] not in {'trained', 'synthetic'} or not model['model_id']:
            raise ContractError('medical_identity_required')
        if model['mode'] == 'synthetic' and os.environ.get('PAIR_AKI_ALLOW_SYNTHETIC') != '1':
            raise ContractError('synthetic_medical_requires_explicit_opt_in')


def verify_record(record, request, admitted):
    if record['request'] != request or record['status'] not in TERMINAL:
        raise ContractError('run_binding')
    result = record['result']
    if not result:
        if record['status'] != 'failed':
            raise ContractError('missing_result')
        return
    require_no_model_scores(result)
    state = result['final_snapshot']
    if (state['case_ref'] != request['case_ref'] or
            state['patient_ref'] != admitted['patient_ref'] or
            state['decision_time'] != admitted['decision_time']):
        raise ContractError('result_case_binding')
    if result['versions']['source_sha256'] != admitted['capabilities']['source']['sha256']:
        raise ContractError('source_changed')
    verify_references(result['narrative'], result['evidence'])
    prediction = result.get('prediction')
    if prediction:
        if type(prediction['label']) is not int or prediction['label'] not in (0, 1):
            raise ContractError('binary_label_required')
        check_receipt(prediction['receipt'], 'M_P', state['snapshot_ref'], admitted['capabilities'])
    comparable = result.get('comparables')
    if comparable:
        matches = comparable['matches']
        patients = [r['patient_ref'] for r in matches]
        if len(matches) > 3 or len(set(patients)) != len(patients) or state['patient_ref'] in patients:
            raise ContractError('reference_patient_isolation')
        for receipt in comparable['receipts']:
            check_receipt(receipt, 'M_R', state['snapshot_ref'], admitted['capabilities'])


def check_receipt(receipt, role, snapshot_ref, caps):
    model = caps['medical_models'][role]
    if (receipt['role'] != role or receipt['model_id'] != model['model_id'] or receipt['mode'] != model['mode'] or
            receipt['input_sha256' if role == 'M_P' else 'query_sha256'] != snapshot_ref or
            receipt['bundle_sha256'] != model.get('bundle_sha256')):
        raise ContractError('medical_receipt_identity')


def execute(tool, request, previous, client, folder):
    validate_request(request)
    if tool not in TOOLS or set(previous) != set(TOOLS[:TOOLS.index(tool)]):
        raise ContractError('stage_sequence')
    for name, receipt in previous.items():
        if receipt['tool'] != name or receipt['input_sha256'] != digest(request) or receipt['output_sha256'] != digest(receipt['output']):
            raise ContractError('predecessor_integrity')
    if tool == 'admit_case':
        caps = client.call('/capabilities')
        validate_capabilities(caps)
        snapshot = client.call('/cases/' + quote(request['case_ref'], safe=''))
        if snapshot['snapshot_ref'] != request['snapshot_ref'] or snapshot['case_ref'] != request['case_ref']:
            raise ContractError('stale_snapshot')
        output = {k: snapshot[k] for k in ('case_ref', 'snapshot_ref', 'patient_ref', 'source_kind', 'decision_time')}
        output['capabilities'] = caps
    elif tool == 'execute_assessment':
        if client.call('/capabilities') != previous['admit_case']['output']['capabilities']:
            raise ContractError('capabilities_changed')
        # An ambiguous HTTP outcome must never cause a duplicate medical submission.
        with (folder / 'submission-intent.json').open('x') as stream:
            json.dump({'request_sha256': digest(request)}, stream)
        rid = client.call('/runs', request)['run_id']
        if not re.fullmatch(r'run-[a-f0-9]{32}', rid):
            raise ContractError('inner_run_id')
        (folder / 'inner-run.json').write_text(json.dumps({'run_id': rid}))
        deadline = time.monotonic() + 260
        while time.monotonic() < deadline:
            record = client.call('/runs/' + rid)
            if record['status'] in TERMINAL:
                break
            time.sleep(.3)
        else:
            raise ContractError('inner_run_timeout')
        output = {'inner_run_id': rid, 'status': record['status'], 'record_sha256': digest(record)}
    else:
        execution = previous['execute_assessment']['output']
        record = client.call('/runs/' + execution['inner_run_id'])
        if digest(record) != execution['record_sha256']:
            raise ContractError('inner_record_changed')
        verify_record(record, request, previous['admit_case']['output'])
        with (folder / 'verified-result.json').open('x') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
        output = {**execution, 'status': 'verified', 'application_status': record['status']}
    return {'tool': tool, 'input_sha256': digest(request), 'output_sha256': digest(output), 'output': output}


def main():
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ContractError('bridge_input_budget')
    payload = json.loads(raw)
    request = json.loads(Path(os.environ['PAIR_AKI_REQUEST']).read_text())
    previous = {name: json.loads(value) for name, value in payload['previous'].items()}
    result = execute(payload['tool'], request, previous, Client(os.environ['PAIR_AKI_API_URL']),
                     Path(os.environ['PAIR_AKI_RUN_DIR']))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
