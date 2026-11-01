"""Optional trained-model endpoints; adapters/weights and private training data are not shipped."""
import copy
import threading
from pair_aki.backend.domain import ContractError
from pair_aki.specialists.contracts import validate_input, validate_result
from pair_aki.specialists.support import support_eligibility
from .transport import local_url, request_json


class MedicalEndpoint:
    mode = 'trained'

    def __init__(self, url, role):
        if role not in {'M_P', 'M_R'}:
            raise ContractError('medical_role')
        self.url, self.role = local_url(url), role
        self.identity = request_json(self.url + '/identity')
        self.model_id = self.identity['model_id']
        self.bundle_sha256 = self.identity['bundle_sha256']
        self._local = threading.local()
        if (self.identity['role'] != role or self.identity['mode'] != 'trained'
                or len(self.bundle_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.bundle_sha256)):
            raise ContractError('medical_identity')

    def validate_support(self, state):
        validate_input(state, synthetic=True)
        if not support_eligibility(state, self.identity['support_signature'])[0]:
            raise ContractError('outside_model_population')

    def _invoke(self, states, timeout):
        from dataclasses import asdict
        for state in states:
            self.validate_support(state)
        if request_json(self.url + '/identity', timeout=min(timeout, 10)) != self.identity:
            raise ContractError('medical_identity_changed')
        endpoint = '/predict' if self.role == 'M_P' else '/compare'
        result = request_json(self.url + endpoint, {'states': [asdict(s) for s in states]}, timeout=timeout)
        validate_result(result, self.role, states, mode='trained', model_id=self.model_id,
                        bundle_sha256=self.bundle_sha256)
        self._local.audit = {'identity': self.identity, 'response': copy.deepcopy(result)}
        return result

    def predict(self, state, *, timeout):
        if self.role != 'M_P':
            raise ContractError('wrong_medical_role')
        return self._invoke((state,), timeout)

    def compare(self, query, left, right, *, timeout):
        if self.role != 'M_R':
            raise ContractError('wrong_medical_role')
        return self._invoke((query, left, right), timeout)

    def last_private_audit(self):
        return copy.deepcopy(getattr(self._local, 'audit', None))
