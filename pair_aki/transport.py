"""Bounded loopback JSON transport; secrets stay outside persisted request receipts."""
import json
import os
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from pair_aki.backend.domain import ContractError, digest
from pair_aki.backend.tool_contracts import ModelResponseError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ContractError('redirect_not_allowed')


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or not parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ContractError('controlled_loopback_endpoint_required')
    return value.rstrip('/')


def request_json(url, payload=None, *, timeout=15, api_key=None):
    local_url(url)
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(url, data=data, headers=headers), timeout=timeout) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ContractError('response_size_limit')
    return json.loads(raw)


class JsonModelClient:
    """OpenAI-compatible chat endpoint, not an OpenAI-hosted dependency."""
    def __init__(self, base_url, model_id, *, api_key=None):
        self.base_url = local_url(base_url)
        if not model_id or len(model_id) > 200:
            raise ContractError('coordinator_model_id_required')
        self.model_id = model_id
        self.api_key = api_key if api_key is not None else os.environ.get('PAIR_AKI_MODEL_API_KEY')

    def complete(self, system, body, schema, *, timeout=70):
        content = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(content.encode()) > 24_000:
            raise ContractError('context_limit_without_truncation')
        payload = {'model': self.model_id, 'temperature': 0, 'max_tokens': 768, 'stream': False,
                   'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'pair_aki_action', 'strict': True, 'schema': schema}}}
        raw = request_json(self.base_url + '/chat/completions', payload, timeout=timeout, api_key=self.api_key)
        receipt = {'model_id': self.model_id, 'mode': 'live', 'raw_response': raw,
                   'request_sha256': digest(payload), 'usage': raw.get('usage', {})}
        try:
            choice = raw['choices'][0]
            if raw['model'] != self.model_id or choice['finish_reason'] != 'stop':
                raise ValueError('model_identity_or_completion')
            return json.loads(choice['message']['content']), receipt
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            raise ModelResponseError('invalid_coordinator_response', receipt) from exc

    def select_statements(self, statements, *, timeout=70):
        ids = [row['id'] for row in statements]
        schema = {'type':'object','properties':{'ordered_ids':{'type':'array','items':{'type':'string','enum':ids},
                  'minItems':len(ids),'maxItems':len(ids)}},'required':['ordered_ids'],'additionalProperties':False}
        output, receipt = self.complete('Order the supplied verified statements. Return only their IDs. Do not add or rewrite content.',
                                        {'statements':statements},schema,timeout=timeout)
        ordered=output.get('ordered_ids') if isinstance(output,dict) else None
        if not isinstance(ordered,list) or len(ordered)!=len(ids) or set(ordered)!=set(ids):
            raise ModelResponseError('statement_identity_changed',receipt)
        by_id={row['id']:row for row in statements}
        return [by_id[key] for key in ordered],receipt
