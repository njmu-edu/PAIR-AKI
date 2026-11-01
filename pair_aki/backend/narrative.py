"""Reference resolution for verified application statements."""
from .domain import ContractError


def verify_references(rows, evidence):
    refs = {x["ref"] for x in evidence}
    if any(not r["evidence_refs"] or not set(r["evidence_refs"]) <= refs for r in rows):
        raise ContractError("unresolved_narrative_reference")
