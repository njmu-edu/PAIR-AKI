"""Postconditions over real current receipts, never an advance tool route."""
from .state import OUTCOME_TOOL


def terminal_postconditions(outcomes, handled, errors, auxiliary_errors, snapshot_ref,
                            available_sources, seen, attempts):
    if not outcomes or any(name not in handled and name not in errors for name in outcomes):
        return None
    receipts = {}
    for name in outcomes:
        value = errors.get(name, handled.get(name))
        input_sha = value.get("admission", {}).get("input_sha256", value.get("input_sha256"))
        if input_sha != snapshot_ref:
            return None
        status = value["status"]
        if status == "failed":
            # Preserve the model's right to choose a retry after the first
            # transient failure. Budget exhaustion is not manufactured success.
            if value["error"]["retryable"] and attempts.get((OUTCOME_TOOL[name], snapshot_ref), 0) < 2:
                return None
        elif status not in {"complete", "blocked"}:
            return None
        receipts[name] = {"status": status, "input_sha256": input_sha}
    if auxiliary_errors:
        # A source failure may justify an explicit model-selected early finish,
        # but cannot be silently promoted to exhausted evidence or auto-success.
        return None
    if (any(r["status"] == "blocked" for r in receipts.values()) and available_sources
            and ("get_evidence", snapshot_ref) not in seen):
        return None
    code = ("failed_tool" if any(r["status"] == "failed" for r in receipts.values()) else
            "blocked_inputs" if any(r["status"] == "blocked" for r in receipts.values()) else "completed")
    return {"code": code, "snapshot_ref": snapshot_ref, "receipts": receipts,
            "origin": "runtime_postconditions"}
