"""Train-only qualified patient recall and deterministic comparisons."""
from pair_aki.backend.domain import ContractError, FEATURE_GROUPS, FEATURE_LABELS, digest
from pair_aki.specialists.contracts import comparison_eligibility
from pair_aki.specialists.supervision import ThreeGroupRule
from .state import factual_view, patient_ref


class ReferenceIndex:
    version = "comparable-recall-v1"

    def __init__(self, references):
        if not references or any(s.split != "train" for s in references):
            raise ContractError("reference_train_only")
        for state in references:
            state.validate()
        if len({s.case_ref for s in references}) != len(references):
            raise ContractError("duplicate_reference_id")
        self.references = tuple(s for s in references if comparison_eligibility(s)[0])
        self.rule = ThreeGroupRule(list(self.references))
        self.identity = digest({"version": self.version, "rule": self.rule.identity,
                                "references": [s.snapshot_ref for s in self.references]})

    def recall(self, query, limit=12):
        if type(limit) is not int or not 1 <= limit <= 12:
            raise ContractError("recall_limit")
        by_patient = {}
        for candidate in self.references:
            if query.patient_ref == candidate.patient_ref:
                continue
            score = self.rule.score(query, candidate)
            previous = by_patient.get(candidate.patient_ref)
            if previous is None or (-score, candidate.case_ref) < (-previous["score"], previous["state"].case_ref):
                by_patient[candidate.patient_ref] = {"state": candidate, "score": score}
        return sorted(by_patient.values(), key=lambda item: (-item["score"], item["state"].case_ref))[:limit]

    def describe(self, query, candidate, rank):
        q, c, comparisons = query.features(), candidate.features(), []
        for names in FEATURE_GROUPS.values():
            for name in names:
                a, b, bounds = q[name], c[name], self.rule.ranges[name]
                delta = None
                if a is not None and b is not None and bounds is not None:
                    span = bounds[1] - bounds[0]
                    delta = min(abs(a - b) / span, 1.) if span else float(a != b)
                comparisons.append({"key": name, "label": FEATURE_LABELS[name], "query": a, "candidate": b,
                                    "distance": delta, "status": "missing" if delta is None else "compared"})
        compared = [r for r in comparisons if r["distance"] is not None]
        return {"rank": rank, "case_ref": candidate.case_ref, "snapshot_ref": candidate.snapshot_ref,
                "patient_ref": patient_ref(candidate), "source_kind": candidate.source_kind,
                "decision_time": candidate.decision_time, "coverage": len(compared) / len(comparisons),
                "similarities": sorted(compared, key=lambda r: r["distance"])[:3],
                "differences": sorted(compared, key=lambda r: r["distance"], reverse=True)[:3],
                "missing": [r["label"] for r in comparisons if r["distance"] is None],
                "observations": factual_view(candidate)["observations"],
                "evidence_refs": [r["ref"] for r in candidate.observations]}
