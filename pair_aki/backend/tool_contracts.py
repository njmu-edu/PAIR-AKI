"""Tool-boundary admission, safe failure classes, and feedback for the next action."""
import copy
import urllib.error
from .domain import ContractError


class InjectedToolTimeout(TimeoutError):
    """Explicit synthetic stress fault, distinguishable from an actual outage."""


class ModelResponseError(ContractError):
    def __init__(self, code, receipt):
        super().__init__(code)
        self.receipt = receipt


def failure(exc):
    retryable = isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))
    if isinstance(exc, urllib.error.HTTPError):
        retryable = exc.code in {408, 429, 502, 503, 504}
    return {"type": type(exc).__name__, "retryable": retryable,
            "category": "synthetic_fault" if isinstance(exc, InjectedToolTimeout) else
                        "contract_rejected" if isinstance(exc, (ContractError, ValueError, TypeError, KeyError)) else
                        "transport_failure" if retryable else "internal_failure",
            **({"http_status": exc.code} if isinstance(exc, urllib.error.HTTPError) else {})}


def acquire_evidence(repository, previous):
    # Isolate even a buggy in-process tool from the accepted input object.
    original = copy.deepcopy(previous)
    candidate = repository.acquire(copy.deepcopy(previous))
    candidate.validate()
    scope = ("case_ref", "patient_ref", "episode_ref", "decision_time", "age_days",
             "hours_since_admission", "source_kind", "gap_id", "version", "endpoint")
    if any(getattr(candidate, name) != getattr(original, name) for name in scope):
        raise ContractError("acquired_evidence_scope_changed")
    retained = {r["ref"]: r for r in candidate.observations}
    if any(retained.get(r["ref"]) != r for r in original.observations):
        raise ContractError("acquired_evidence_rewrote_accepted_fact")
    # Current evidence contract is append-only. Source corrections require a new
    # explicitly admitted revision, not silent rewriting through a retrieval tool.
    return copy.deepcopy(candidate)


def feedback_summary(tool, result, snapshot_ref):
    summary = {"tool": tool, "status": result["status"], "reason": result.get("reason"),
               "input_sha256": snapshot_ref}
    if tool == "predict_risk":
        summary.update({k: result.get(k) for k in ("probability", "raw_probability", "mode", "model_id", "endpoint")})
    elif tool == "find_similar":
        summary.update(index_sha256=result["index_sha256"], matches=[
            {k: m[k] for k in ("case_ref", "snapshot_ref", "score", "coverage", "similarities", "differences", "missing")}
            for m in result["matches"]])
    elif tool == "get_evidence":
        summary.update(snapshot_ref=result["snapshot_ref"], evidence_complete=result["state"]["evidence_complete"],
                       prediction_eligible=result["state"]["prediction_eligible"],
                       eligibility_reason=result["state"]["eligibility_reason"])
    return summary
