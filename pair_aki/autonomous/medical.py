"""Qualified medical calls, private numeric audit, and independently trained reranking."""
import copy
from itertools import combinations
import math
import threading
import time
from pair_aki.backend.domain import ContractError
from pair_aki.backend.tool_contracts import failure, InjectedToolTimeout
from pair_aki.specialists.contracts import validate_result
from .state import admit


class MedicalTools:
    def __init__(self, repository, index, predictor, comparator, ledger):
        self.repository, self.index = repository, index
        self.predictor, self.comparator, self.ledger = predictor, comparator, ledger
        self.locks = {"M_P": threading.Lock(), "M_R": threading.Lock()}

    def inspect_admissions(self, snapshot):
        """Actual contract checks returned by state/evidence tools; no model forward."""
        checked = {}
        for role, provider in (("M_P", self.predictor), ("M_R", self.comparator)):
            gate = admit(snapshot, role, self.repository.sources(snapshot))
            if gate["admitted"]:
                try:
                    provider.validate_support(copy.deepcopy(snapshot))
                    gate["model_support"] = "accepted"
                except ContractError as exc:
                    gate.update(admitted=False, model_support="contract_rejected", reason=str(exc))
            checked[role] = gate
        return checked

    def _invoke(self, role, states, deadline, rid, metrics):
        provider = self.predictor if role == "M_P" else self.comparator
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("medical_deadline_before_call")
        if not self.locks[role].acquire(timeout=remaining):
            raise TimeoutError("medical_queue_deadline")
        refs = dict(zip(("input_sha256",) if role == "M_P" else ("query_sha256", "left_sha256", "right_sha256"),
                        (s.snapshot_ref for s in states)))
        metadata = {"role": role, "mode": provider.mode, "model_id": provider.model_id,
                    "input_refs": refs, "attempted": True, "forward_count": 0}
        metrics["medical_attempts"] += 1
        result = None
        entered_provider = False
        try:
            if self.repository.inject_failure(states[0], role):
                raise InjectedToolTimeout("explicit_synthetic_fault_before_forward")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("medical_deadline_after_queue")
            entered_provider = True
            if role == "M_P":
                result = provider.predict(copy.deepcopy(states[0]), timeout=remaining)
            else:
                result = provider.compare(*(copy.deepcopy(s) for s in states), timeout=remaining)
            metadata["forward_count"] = 1
            metrics["predictor_forwards" if role == "M_P" else "comparator_forwards"] += 1
            validate_result(result, role, states, mode=provider.mode, model_id=provider.model_id,
                            bundle_sha256=getattr(provider, "bundle_sha256", None))
            if role == "M_R" and result["choice"] != ("A" if result["margin"] >= 0 else "B"):
                raise ContractError("choice_margin_disagree")
            metadata["status"] = "complete"
            metadata["receipt"] = copy.deepcopy(result["receipt"])
            audit = self.ledger.private_medical_audit(rid, {"call": metadata, "result": result,
                                                          "native_audit": provider.last_private_audit()})
            self.ledger.event(rid, {"kind": "medical_call", "status": "complete", "details": {**metadata, **audit}})
            return result
        except Exception as exc:
            if entered_provider and result is None:
                # A failed transport/model call does not establish whether GPU work ran.
                metadata["forward_count"] = getattr(exc, "confirmed_forward_count", None)
                if metadata["forward_count"] is None:
                    metrics["medical_forward_unknown"] += 1
                elif metadata["forward_count"]:
                    metrics["predictor_forwards" if role == "M_P" else "comparator_forwards"] += metadata["forward_count"]
            metadata.update(status="failed", **failure(exc))
            audit = self.ledger.private_medical_audit(rid, {"call": metadata, "result": result,
                    "native_audit": provider.last_private_audit() if entered_provider else None})
            self.ledger.event(rid, {"kind": "medical_call", "status": "failed", "details": {**metadata, **audit}})
            raise
        finally:
            self.locks[role].release()

    def predict(self, snapshot, deadline, rid, metrics):
        gate = admit(snapshot, "M_P", self.repository.sources(snapshot))
        if not gate["admitted"]:
            return {"status": "blocked", "reason": gate["reason"], "admission": gate}
        self.predictor.validate_support(copy.deepcopy(snapshot))
        result = self._invoke("M_P", (snapshot,), deadline, rid, metrics)
        return {"status": "complete", "prediction": result, "admission": gate}

    def retrieve(self, snapshot, deadline, rid, metrics):
        gate = admit(snapshot, "M_R", self.repository.sources(snapshot))
        if not gate["admitted"]:
            return {"status": "blocked", "reason": gate["reason"], "admission": gate}
        self.comparator.validate_support(copy.deepcopy(snapshot))
        candidates = self.index.recall(snapshot)
        if not candidates:
            return {"status": "blocked", "reason": "no_qualified_reference_patients", "admission": gate}
        for candidate in candidates:
            self.comparator.validate_support(copy.deepcopy(candidate["state"]))
        points = {item["state"].case_ref: 0. for item in candidates}
        receipts, inconsistencies = [], 0
        for left, right in combinations(candidates, 2):
            a, b = left["state"], right["state"]
            ab = self._invoke("M_R", (snapshot, a, b), deadline, rid, metrics)
            ba = self._invoke("M_R", (snapshot, b, a), deadline, rid, metrics)
            receipts.extend((ab["receipt"], ba["receipt"]))
            combined = (ab["margin"] - ba["margin"]) / 2
            if not math.isfinite(combined):
                raise ContractError("nonfinite_pair_aggregation")
            inconsistencies += int((ab["margin"] > 0) == (ba["margin"] > 0) and ab["margin"] != 0 and ba["margin"] != 0)
            if combined > 0:
                points[a.case_ref] += 1
            elif combined < 0:
                points[b.case_ref] += 1
            else:
                points[a.case_ref] += .5
                points[b.case_ref] += .5
        ordered = sorted(candidates, key=lambda item: (-points[item["state"].case_ref], -item["score"], item["state"].case_ref))
        matches = [self.index.describe(snapshot, item["state"], i + 1) for i, item in enumerate(ordered[:3])]
        result = {"status": "complete" if len(matches) == 3 else "partial", "matches": matches,
                  "receipts": receipts, "index_version": self.index.version, "index_sha256": self.index.identity,
                  "candidate_count": len(candidates), "pair_forwards": len(receipts),
                  "inconsistent_presentations": inconsistencies,
                  "reason": None if len(matches) == 3 else "fewer_than_three_qualified_patients",
                  "model_used": bool(receipts)}
        return {"status": "complete", "comparables": result, "admission": gate}
