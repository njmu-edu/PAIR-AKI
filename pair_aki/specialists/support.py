"""G2-pinned population signature for execution-layer model eligibility."""
from pair_aki.backend.domain import ContractError, ENDPOINT, VERSION, finite
from .contracts import validate_input


def validate_signature(signature, role, cohort_id):
    if (role not in {"M_P", "M_R"} or not isinstance(cohort_id, str) or not cohort_id
            or not isinstance(signature, dict) or set(signature) != {"version", "role", "cohort_id", "population_id",
            "snapshot_version", "endpoint", "age_days_min", "age_days_max"}
            or signature["version"] != "specialist-support-v1" or signature["role"] != role
            or signature["cohort_id"] != cohort_id or signature["snapshot_version"] != VERSION
            or signature["endpoint"] != ENDPOINT or not isinstance(signature["population_id"], str)
            or not signature["population_id"] or not finite(signature["age_days_min"])
            or not finite(signature["age_days_max"])
            or not 0 <= signature["age_days_min"] <= signature["age_days_max"]):
        raise ContractError("model_support_signature_unqualified")


def support_eligibility(snapshot, signature):
    """No invented clinical thresholds: the caller supplies the registered signature."""
    validate_input(snapshot)
    if not isinstance(signature, dict):
        raise ContractError("model_support_signature_unqualified")
    validate_signature(signature, signature.get("role"), signature.get("cohort_id"))
    if not signature["age_days_min"] <= snapshot.age_days <= signature["age_days_max"]:
        return False, "outside_registered_model_population"
    return True, None
