"""Neutral synthetic cases; evaluator truth is never exposed to the coordinator."""
from dataclasses import replace
import copy
from pair_aki.backend.synthetic import make_case, SyntheticRepository as PreviousExamples
from pair_aki.backend.domain import ContractError, digest
from .state import factual_view, patient_ref


class SyntheticRepository:
    mode = "synthetic"
    version = "autonomous-fixtures-v1"

    def __init__(self):
        self.labels = {"ae-201": 1, "ae-202": 0, "ae-203": 1, "ae-204": 0}
        self.references = [replace(s, label="历史参考病例") for s in PreviousExamples().references]
        # Twelve distinct reference patients, plus one alternative timepoint.
        for n in range(7, 13):
            self.references.append(make_case(f"ref-{n:02}", "历史参考病例", 900 + n * 120,
                                            [30+n, 31+n, 32+n, 33+n, 35+n, 37+n], split="train"))
        self.cases, self.expanded = {}, {}
        for n in range(201, 211):
            ref = f"ae-{n}"
            values = [35, 36, 37, 39, 42, 45] if n % 2 else [40, 41, 40, 42, 43, 43]
            full = make_case(ref, "合成病例", 1460 if n % 2 else 1825, values)
            state = full
            if n in (203, 204):
                state = replace(full, observations=(full.observations[-1],), evidence_complete=False)
                self.expanded[ref] = full
            elif n in (205, 206):
                state = replace(full, observations=(full.observations[-1],))
            elif n in (207, 208):
                state = replace(full, observations=full.observations[:-1] + (
                    {**full.observations[-1], "value": None, "status": "conflict"},))
            state.validate()
            self.cases[ref] = state
        self.identity = digest({"version": self.version, "initial": [s.snapshot_ref for s in self.cases.values()],
                                "expanded": [s.snapshot_ref for s in self.expanded.values()],
                                "reference": [s.snapshot_ref for s in self.references]})

    def list_cases(self):
        return [factual_view(s) for s in self.cases.values()]

    def get(self, case_ref, snapshot_ref=None):
        if case_ref not in self.cases:
            raise ContractError("case_not_found")
        result = self.cases[case_ref]
        if snapshot_ref is not None and result.snapshot_ref != snapshot_ref:
            raise ContractError("snapshot_version_mismatch")
        return copy.deepcopy(result)

    def sources(self, state):
        return ["registered_history"] if state.case_ref in self.expanded and state.snapshot_ref != self.expanded[state.case_ref].snapshot_ref else []

    def source_catalog(self, state):
        """Registered source metadata, without values, outcomes or a proposed route."""
        if not self.sources(state):
            return []
        target = self.expanded[state.case_ref]
        # Snapshot.rows validates source kind, episode/time, units and revision
        # status under the existing contract; no invented observation fields.
        rows = target.rows()
        existing = {r["ref"] for r in state.observations}
        return [{"source_ref": "registered_history", "source_kind": "synthetic",
                 "content": "Historical serum-creatinine observations for the same patient and admission, available as of this assessment.",
                 "access": "already_authorized_read_only", "gap_id": state.gap_id,
                 "qualified_record_count": len(rows),
                 "records_not_yet_loaded": sum(r["ref"] not in existing for r in rows),
                 "event_hours_range": [min(r["event_hours"] for r in rows), max(r["event_hours"] for r in rows)] if rows else None,
                 "retrieval_result": "not_yet_observed"}]

    def acquire(self, state):
        return copy.deepcopy(self.expanded.get(state.case_ref, state))

    def inject_failure(self, state, role):
        return state.source_kind == "synthetic" and state.case_ref in {"ae-209", "ae-210"} and role in {"M_P", "M_R"}

    def evaluation_manifest(self):
        """Offline evaluator only; never register this method as a tool or API."""
        from .recall import ReferenceIndex
        cases = {}
        for ref, state in self.cases.items():
            final = self.expanded.get(ref, state)
            cases[ref] = {"patient_ref": patient_ref(state), "initial_snapshot_ref": state.snapshot_ref,
                          "final_snapshot_ref": final.snapshot_ref, "expected_label": self.labels.get(ref),
                          "evidence_refs": [r["ref"] for r in final.observations]}
        references = {s.case_ref: {"patient_ref": patient_ref(s), "snapshot_ref": s.snapshot_ref,
                                  "evidence_refs": [r["ref"] for r in s.observations]} for s in self.references}
        return {"schema_version": "autonomous-eval-fixtures-v1", "source_kind": "synthetic",
                "source_version": self.version, "source_sha256": self.identity,
                "reference_index_sha256": ReferenceIndex(self.references).identity,
                "cases": cases, "references": references}
