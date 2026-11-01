"""Public factual views and task-specific admission, outside medical models."""
from dataclasses import dataclass
import copy
import math
from pair_aki.backend.domain import Snapshot, ContractError, digest
from pair_aki.specialists.contracts import comparison_eligibility, CONTRACTS

VERSION = "autonomous-state-v1"
OUTCOMES = ("event_prediction", "comparable_cases")
TOOLS = ("read_case_state", "get_evidence", "predict_event_24h", "retrieve_comparable_cases")
OUTCOME_TOOL = {"event_prediction": "predict_event_24h", "comparable_cases": "retrieve_comparable_cases"}


@dataclass(frozen=True)
class Budget:
    seconds: float = 240
    tools: int = 6
    coordinator: int = 8
    repairs: int = 2

    def __post_init__(self):
        if (type(self.seconds) not in (int, float) or not math.isfinite(self.seconds) or self.seconds < 0
                or any(type(v) is not int or v < 0 for v in (self.tools, self.coordinator, self.repairs))):
            raise ContractError("invalid_autonomous_budget")


def patient_ref(snapshot):
    return digest({"patient": snapshot.patient_ref, "source": snapshot.source_kind})


def factual_view(snapshot):
    """No scenario labels, qualification answers, route hints, scores or outcomes."""
    snapshot.validate()
    return {"case_ref": snapshot.case_ref, "snapshot_ref": snapshot.snapshot_ref,
            "patient_ref": patient_ref(snapshot), "source_kind": snapshot.source_kind,
            "decision_time": snapshot.decision_time, "age_days": snapshot.age_days,
            "hours_since_admission": snapshot.hours_since_admission,
            "observations": copy.deepcopy(list(snapshot.observations)), "features": snapshot.features(),
            "endpoint": snapshot.endpoint, "version": snapshot.version}


def admit(snapshot, role, sources):
    snapshot.validate()
    if role not in CONTRACTS:
        raise ContractError("unknown_medical_role")
    ok, reason = snapshot.eligibility() if role == "M_P" else comparison_eligibility(snapshot)
    return {"admitted": ok, "role": role, "input_sha256": snapshot.snapshot_ref,
            "contract_version": CONTRACTS[role], "reason": reason,
            "available_sources": list(sources), "source_kind": snapshot.source_kind,
            "version": "harness-medical-admission-v1"}


def require_no_model_scores(value):
    """Business/coordination boundary, including nested model responses."""
    forbidden = {"probability", "raw_probability", "logit", "logits", "margin", "temperature", "calibration_temperature"}
    if isinstance(value, dict):
        if forbidden & set(value):
            raise ContractError("medical_score_at_business_boundary")
        for child in value.values():
            require_no_model_scores(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            require_no_model_scores(child)


def validate_interpretation(value):
    if not isinstance(value, dict) or set(value) != {"outcomes", "clarification"}:
        raise ContractError("goal_interpretation_schema")
    outcomes, clarification = value["outcomes"], value["clarification"]
    if (not isinstance(outcomes, list) or not all(type(x) is str and x in OUTCOMES for x in outcomes)
            or len(set(outcomes)) != len(outcomes)):
        raise ContractError("goal_outcomes_schema")
    if clarification is not None and (not isinstance(clarification, str) or not 1 <= len(clarification.strip()) <= 500):
        raise ContractError("clarification_schema")
    if bool(outcomes) == bool(clarification):
        raise ContractError("goal_requires_outcomes_or_clarification")
    return value
