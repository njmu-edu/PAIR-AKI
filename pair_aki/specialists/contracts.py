"""Role-specific input structure and exact, probability-free service contracts."""
from __future__ import annotations

import math
from typing import Protocol
from pair_aki.backend.domain import Snapshot, ContractError, digest

CONTRACTS = {"M_P": "mp-binary-v1", "M_R": "mr-pair-v1"}
CANDIDATES = {"M_P": ("0", "1"), "M_R": ("A", "B")}


class Predictor(Protocol):
    mode: str
    model_id: str

    def validate_support(self, snapshot: Snapshot) -> None: ...

    def predict(self, snapshot: Snapshot, *, timeout: float) -> dict: ...


class Comparator(Protocol):
    mode: str
    model_id: str

    def validate_support(self, snapshot: Snapshot) -> None: ...

    def compare(self, query: Snapshot, left: Snapshot, right: Snapshot, *, timeout: float) -> dict: ...


def require_timeout(timeout: float) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ContractError("specialist_timeout_must_be_positive")


def validate_input(snapshot: Snapshot, *, synthetic: bool | None = None) -> None:
    if not isinstance(snapshot, Snapshot):
        raise ContractError("specialist_snapshot_type")
    snapshot.validate()
    if synthetic is True and snapshot.source_kind != "synthetic":
        raise ContractError("synthetic_provider_requires_synthetic")
    if synthetic is False and snapshot.source_kind != "approved_research":
        raise ContractError("trained_provider_requires_approved_research")


def comparison_eligibility(snapshot: Snapshot) -> tuple[bool, str | None]:
    """Structural comparison support; prevalent events are allowed for M_R.

    The caller's execution layer applies this gate before a medical call. The
    provider validates identity/structure, and does not re-decide eligibility.
    """
    validate_input(snapshot)
    if not snapshot.evidence_complete or any(r["status"] != "known" for r in snapshot.observations):
        return False, "comparison_evidence_incomplete_or_conflicted"
    rows = [r for r in snapshot.rows() if r["event_hours"] >= -168]
    if len(rows) < 2 or rows[-1]["event_hours"] < -24:
        return False, "comparison_requires_recent_and_historical_creatinine"
    if snapshot.features()["reference168_umol_l"] is None:
        return False, "comparison_requires_historical_reference"
    return True, None


def validate_pair(query: Snapshot, left: Snapshot, right: Snapshot, *, synthetic: bool | None = None) -> None:
    for state in (query, left, right):
        validate_input(state, synthetic=synthetic)
    if len({s.patient_ref for s in (query, left, right)}) != 3:
        raise ContractError("comparison_requires_three_distinct_patients")
    if len({s.source_kind for s in (query, left, right)}) != 1:
        raise ContractError("comparison_mixed_sources")


def receipt(role: str, mode: str, model_id: str, states: tuple[Snapshot, ...], bundle_sha256: str | None) -> dict:
    fields = ("input_sha256",) if role == "M_P" else ("query_sha256", "left_sha256", "right_sha256")
    return {"role": role, "mode": mode, "model_id": model_id, "contract_version": CONTRACTS[role],
            **dict(zip(fields, (s.snapshot_ref for s in states))), "bundle_sha256": bundle_sha256}


def validate_result(result: dict, role: str, states: tuple[Snapshot, ...], *, mode: str, model_id: str,
                    bundle_sha256: str | None = None) -> dict:
    expected_fields = {"label", "receipt"} if role == "M_P" else {"choice", "margin", "receipt"}
    if not isinstance(result, dict) or set(result) != expected_fields:
        raise ContractError("specialist_result_allowlist")
    if mode not in {"synthetic", "trained"} or (mode == "trained") != (bundle_sha256 is not None):
        raise ContractError("specialist_mode_bundle_binding")
    if result["receipt"] != receipt(role, mode, model_id, states, bundle_sha256):
        raise ContractError("specialist_receipt_mismatch")
    if role == "M_P":
        if type(result["label"]) is not int or result["label"] not in (0, 1):
            raise ContractError("prediction_requires_integer_binary_label")
    elif (result["choice"] not in ("A", "B") or isinstance(result["margin"], bool)
          or not isinstance(result["margin"], (int, float)) or not math.isfinite(result["margin"])):
        raise ContractError("comparison_requires_finite_choice_margin")
    elif result["choice"] != ("A" if result["margin"] >= 0 else "B"):
        raise ContractError("comparison_choice_margin_disagree")
    return result


def facts(snapshot: Snapshot) -> dict:
    """Allowlist: no display labels, patient IDs, split, outcome, or follow-up."""
    validate_input(snapshot)
    return {"decision_time": snapshot.decision_time, "age_days": snapshot.age_days,
            "hours_since_admission": snapshot.hours_since_admission,
            "observations": [{k: r[k] for k in ("value", "unit", "event_hours", "available_hours", "status")}
                             for r in sorted(snapshot.observations, key=lambda row: row["event_hours"])],
            "features": snapshot.features()}


def state_content_sha(snapshot: Snapshot) -> str:
    return digest(facts(snapshot))
