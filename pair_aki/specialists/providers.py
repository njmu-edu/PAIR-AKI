"""Explicit engineering doubles; trained models connect through medical_provider.py."""
from __future__ import annotations

from collections import deque
from types import MappingProxyType
import copy
import threading
from pair_aki.backend.domain import digest, ContractError
from .contracts import require_timeout, validate_input, validate_pair, receipt, validate_result, facts


class SyntheticPredictor:
    mode = "synthetic"
    model_id = "M_P-synthetic-contract-v1"

    def __init__(self, labels=None):
        labels = {} if labels is None else dict(labels)
        if any(not isinstance(k, str) or type(v) is not int or v not in (0, 1) for k, v in labels.items()):
            raise ContractError("synthetic_fixture_labels")
        self.labels = MappingProxyType(labels)
        self.private_audit = deque(maxlen=1024)
        self.forward_calls = 0
        self._audit_local = threading.local()

    def validate_support(self, snapshot):
        validate_input(snapshot, synthetic=True)

    def last_private_audit(self):
        return copy.deepcopy(getattr(self._audit_local, "last", None))

    def predict(self, snapshot, *, timeout: float):
        self._audit_local.last = None
        require_timeout(timeout)
        self.validate_support(snapshot)
        # A deterministic fixture, explicitly unrelated to clinical probability.
        label = self.labels.get(snapshot.case_ref, int(digest(facts(snapshot))[-1], 16) % 2)
        self.forward_calls += 1
        proof = receipt("M_P", self.mode, self.model_id, (snapshot,), None)
        audit = {"role": "M_P", "mode": "synthetic", "input_sha256": snapshot.snapshot_ref, "fixture_label": label}
        self.private_audit.append(audit)
        self._audit_local.last = audit
        return validate_result({"label": label, "receipt": proof}, "M_P", (snapshot,),
                               mode=self.mode, model_id=self.model_id)


class SyntheticComparator:
    mode = "synthetic"
    model_id = "M_R-synthetic-contract-v1"

    def __init__(self):
        self.private_audit = deque(maxlen=1024)
        self.forward_calls = 0
        self._audit_local = threading.local()

    def validate_support(self, snapshot):
        validate_input(snapshot, synthetic=True)

    def last_private_audit(self):
        return copy.deepcopy(getattr(self._audit_local, "last", None))

    def compare(self, query, left, right, *, timeout: float):
        self._audit_local.last = None
        require_timeout(timeout)
        validate_pair(query, left, right, synthetic=True)
        for snapshot in (query, left, right):
            self.validate_support(snapshot)
        # This stable double tests ranking plumbing, never clinical similarity.
        def score(candidate):
            return int(digest({"query": facts(query), "candidate": facts(candidate)})[:12], 16) / 16**12
        margin = score(left) - score(right)
        choice = "A" if margin >= 0 else "B"
        self.forward_calls += 1
        proof = receipt("M_R", self.mode, self.model_id, (query, left, right), None)
        audit = {"role": "M_R", "mode": "synthetic", "receipt": proof, "margin": margin}
        self.private_audit.append(audit)
        self._audit_local.last = audit
        return validate_result({"choice": choice, "margin": margin, "receipt": proof}, "M_R",
                               (query, left, right), mode=self.mode, model_id=self.model_id)
