"""Immutable, outcome-free clinical snapshots and source/time validation."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any
import copy
import hashlib
import json
import math

VERSION = "competition-state-v1"
ENDPOINT = "observed-scr-onset-supported-v1"
GAP_ID = "COMP-230-reference-purpose"
FEATURE_GROUPS = {
    "background": ("age_days", "hours_since_admission"),
    "renal_state": ("latest_umol_l", "reference168_umol_l", "ratio168", "rise48_umol_l"),
    "renal_trend": ("slope24_per_hour", "slope72_per_hour", "range72_umol_l"),
}
FEATURE_LABELS = {
    "age_days": "年龄", "hours_since_admission": "入院后时长",
    "latest_umol_l": "当前肌酐", "reference168_umol_l": "既往肌酐基线",
    "ratio168": "相对基线倍数", "rise48_umol_l": "48小时肌酐变化",
    "slope24_per_hour": "24小时变化趋势", "slope72_per_hour": "72小时变化趋势",
    "range72_umol_l": "72小时波动",
}
UNITS = {"umol/L": 1.0, "µmol/L": 1.0, "μmol/L": 1.0, "mg/dL": 88.4}


class ContractError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def slope(rows: list[dict]) -> float | None:
    if len(rows) < 2:
        return None
    xs = [r["event_hours"] for r in rows]
    ys = [r["value"] for r in rows]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = sum((x - xm) ** 2 for x in xs)
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denominator if denominator else None


@dataclass(frozen=True)
class Snapshot:
    case_ref: str
    patient_ref: str
    episode_ref: str
    label: str
    decision_time: str
    age_days: float
    hours_since_admission: float
    observations: tuple[dict, ...]
    split: str = "query"
    source_kind: str = "synthetic"
    gap_id: str = GAP_ID
    evidence_complete: bool = True
    limitations: tuple[str, ...] = ()
    version: str = VERSION
    endpoint: str = ENDPOINT

    def validate(self) -> None:
        if not all(isinstance(x, str) and x for x in
                   (self.case_ref, self.patient_ref, self.episode_ref, self.label)):
            raise ContractError("missing_case_identity")
        if datetime.fromisoformat(self.decision_time.replace("Z", "+00:00")).tzinfo is None:
            raise ContractError("decision_time_requires_timezone")
        if self.version != VERSION or self.endpoint != ENDPOINT:
            raise ContractError("snapshot_contract_mismatch")
        if not isinstance(self.evidence_complete, bool):
            raise ContractError("evidence_complete_requires_boolean")
        if self.source_kind not in {"synthetic", "approved_research"} or self.split not in {"train", "query", "dev"}:
            raise ContractError("source_or_split_not_admitted")
        if self.source_kind == "synthetic" and not self.gap_id:
            raise ContractError("synthetic_requires_gap")
        if not finite(self.age_days) or self.age_days < 0 or not finite(self.hours_since_admission) or self.hours_since_admission < 0:
            raise ContractError("invalid_background")
        seen, event_values = set(), {}
        for row in self.observations:
            if set(row) != {"ref", "value", "unit", "event_hours", "available_hours", "status"}:
                raise ContractError("observation_allowlist")
            if row["ref"] in seen or not isinstance(row["ref"], str) or not row["ref"]:
                raise ContractError("duplicate_or_missing_evidence")
            seen.add(row["ref"])
            if row["unit"] not in UNITS or row["status"] not in {"known", "conflict"}:
                raise ContractError("unqualified_unit_or_status")
            if not finite(row["event_hours"]) or not finite(row["available_hours"]):
                raise ContractError("invalid_clock")
            if not -self.hours_since_admission <= row["event_hours"] <= row["available_hours"] <= 0:
                raise ContractError("future_or_wrong_episode_observation")
            if row["status"] == "known" and (not finite(row["value"]) or row["value"] <= 0):
                raise ContractError("invalid_creatinine")
            if row["status"] == "conflict" and row["value"] is not None:
                raise ContractError("conflicted_value_must_be_unknown")
            value = None if row["value"] is None else round(row["value"] * UNITS[row["unit"]], 10)
            if row["event_hours"] in event_values:
                raise ContractError("duplicate_event_requires_source_adjudication")
            event_values[row["event_hours"]] = value

    @property
    def snapshot_ref(self) -> str:
        self.validate()
        return digest(asdict(self))

    def rows(self) -> list[dict]:
        self.validate()
        return sorted(({**r, "value": r["value"] * UNITS[r["unit"]], "unit": "umol/L"}
                       for r in self.observations if r["status"] == "known"), key=lambda r: (r["event_hours"], r["ref"]))

    def features(self) -> dict[str, float | None]:
        rows = self.rows()
        latest = rows[-1] if rows else None
        anchor = latest["event_hours"] if latest else 0
        prior7 = [r["value"] for r in rows if anchor - 168 <= r["event_hours"] < anchor]
        prior2 = [r["value"] for r in rows if anchor - 48 <= r["event_hours"] < anchor]
        base7, base2 = (min(prior7) if prior7 else None), (min(prior2) if prior2 else None)
        win24 = [r for r in rows if -24 < r["event_hours"] <= 0]
        win72 = [r for r in rows if -72 < r["event_hours"] <= 0]
        last = latest["value"] if latest else None
        return {
            "age_days": self.age_days, "hours_since_admission": self.hours_since_admission,
            "latest_umol_l": last, "reference168_umol_l": base7,
            "ratio168": last / base7 if last is not None and base7 else None,
            "rise48_umol_l": last - base2 if last is not None and base2 is not None else None,
            "slope24_per_hour": slope(win24), "slope72_per_hour": slope(win72),
            "range72_umol_l": max(r["value"] for r in win72) - min(r["value"] for r in win72) if win72 else None,
        }

    def eligibility(self) -> tuple[bool, str | None]:
        self.validate()
        if any(r["status"] == "conflict" for r in self.observations):
            return False, "存在未解决的肌酐记录冲突"
        f = self.features()
        if f["latest_umol_l"] is None or f["reference168_umol_l"] is None:
            return False, "当前值或合格的既往基线不足"
        rows = self.rows()
        if rows[-1]["event_hours"] < -24:
            return False, "最近肌酐记录距评估时点超过24小时"
        for row in rows:
            prior7 = [Decimal(str(r["value"])) for r in rows
                      if row["event_hours"] - 168 <= r["event_hours"] < row["event_hours"]]
            prior2 = [Decimal(str(r["value"])) for r in rows
                      if row["event_hours"] - 48 <= r["event_hours"] < row["event_hours"]]
            value = Decimal(str(row["value"]))
            if prior7 and (value >= Decimal("1.5") * min(prior7) or
                           (prior2 and value - min(prior2) >= Decimal("26.5"))):
                return False, "既往或当前已满足本研究肌酐事件判据，不适用新发风险任务"
        if not self.evidence_complete:
            return False, "已有可获取资料尚未核齐"
        return True, None

    def public(self) -> dict:
        eligible, reason = self.eligibility()
        return {
            "case_ref": self.case_ref, "snapshot_ref": self.snapshot_ref, "label": self.label,
            "decision_time": self.decision_time, "age_days": self.age_days,
            "hours_since_admission": self.hours_since_admission,
            "source_kind": self.source_kind, "gap_id": self.gap_id,
            "features": self.features(), "observations": copy.deepcopy(list(self.observations)),
            "prediction_eligible": eligible, "eligibility_reason": reason,
            "evidence_complete": self.evidence_complete, "limitations": list(self.limitations),
            "endpoint": self.endpoint, "version": self.version,
        }
