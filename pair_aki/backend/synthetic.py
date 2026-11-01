"""Explicit synthetic examples: no actual patient records or learned predictions."""
from __future__ import annotations
from dataclasses import replace
from .domain import Snapshot, ContractError


def make_case(ref, label, age, values, *, split="query", patient=None, times=None,
              complete=True, limitations=()):
    times = times or [-144, -72, -48, -24, -12, 0]
    rows = tuple({"ref": f"{ref}:scr:{i}", "value": float(value), "unit": "umol/L",
                  "event_hours": float(hour), "available_hours": float(hour),
                  "status": "known"} for i, (hour, value) in enumerate(zip(times, values)))
    result = Snapshot(ref, patient or ref, f"{ref}:admission", label,
                      "2026-01-15T08:00:00+08:00", age, 192, rows, split=split,
                      evidence_complete=complete, limitations=tuple(limitations))
    result.validate()
    return result


class SyntheticRepository:
    mode = "synthetic"

    def __init__(self):
        reference = [
            ("ref-01", "参考病例 01", 1500, [35, 36, 37, 39, 40, 43]),
            ("ref-02", "参考病例 02", 1300, [36, 37, 38, 40, 42, 45]),
            ("ref-03", "参考病例 03", 2400, [42, 41, 42, 43, 45, 46]),
            ("ref-04", "参考病例 04", 3650, [48, 49, 48, 50, 49, 51]),
            ("ref-05", "参考病例 05", 900, [30, 31, 32, 33, 34, 35]),
            ("ref-06", "参考病例 06", 1520, [36, 35, 36, 38, 40, 43]),
        ]
        self.references = [make_case(*r, split="train") for r in reference]
        self.references.append(make_case("ref-01-second", "参考病例01另一时点", 1500,
                                         [36, 37, 38, 40, 41, 44], split="train", patient="ref-01"))
        normal = make_case("demo-01", "病程评估示例", 1460, [35, 36, 37, 39, 42, 45])
        missing_full = make_case("demo-02", "资料补取示例", 1095, [31, 32, 33, 34, 35, 37])
        missing = replace(missing_full, observations=(missing_full.observations[-1],),
                          evidence_complete=False, limitations=("初始视图只显示最近一次肌酐，历史资料可补取",))
        insufficient = make_case("demo-03", "资料不足示例", 1460, [44], times=[0],
                                 limitations=("所有已提供来源均无合格既往基线",))
        occurred = make_case("demo-04", "任务适用性示例", 730, [30, 30, 32, 42, 49, 58])
        failure = make_case("demo-05", "工具失败示例", 1800, [40, 41, 40, 42, 43, 44])
        conflict = make_case("demo-06", "记录冲突示例", 1460, [35, 36, 37, 39, 42, 45])
        conflict = replace(conflict, observations=conflict.observations[:-1] + (
            {**conflict.observations[-1], "value": None, "status": "conflict"},))
        self.cases = {c.case_ref: c for c in (normal, missing, insufficient, occurred, failure, conflict)}
        self.expanded = {"demo-02": missing_full}

    def list_cases(self):
        return [x.public() for x in self.cases.values()]

    def get(self, case_ref, snapshot_ref=None):
        if case_ref not in self.cases:
            raise ContractError("case_not_found")
        result = self.cases[case_ref]
        if snapshot_ref is not None and snapshot_ref != result.snapshot_ref:
            raise ContractError("snapshot_version_mismatch")
        return result

    def acquire(self, current):
        result = self.expanded.get(current.case_ref, current)
        result.validate()
        if result.patient_ref != current.patient_ref or result.decision_time != current.decision_time:
            raise ContractError("evidence_scope_mismatch")
        return result

    def predict_fault(self, case_ref):
        return case_ref == "demo-05"
