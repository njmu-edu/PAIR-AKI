"""V2 terminal states and non-public medical score audit; v1 remains untouched."""
import json
import math
import os
import time
import uuid
from pair_aki.backend.domain import ContractError, digest
from pair_aki.backend.store import RunStore
from .state import require_no_model_scores

TERMINAL = {"succeeded", "partial", "failed", "blocked", "needs_clarification"}


def audit_value(value):
    """Preserve rejected numeric payloads as explicit typed audit data, never a label."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"audit_type": "nonfinite_float", "value": repr(value)}
    if isinstance(value, dict):
        return {key: audit_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [audit_value(child) for child in value]
    return value


class Ledger(RunStore):
    def event(self, rid, event):
        require_no_model_scores(event)
        with self.lock, self.connection() as con:
            row = con.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()
            if not row or row[0] in TERMINAL:
                raise ContractError("terminal_run_is_immutable")
            seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (rid,)).fetchone()[0]
            value = {**event, "seq": seq, "at": time.time()}
            con.execute("INSERT INTO events VALUES(?,?,?)", (rid, seq, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def finish(self, rid, status, result):
        if status not in TERMINAL:
            raise ContractError("terminal_status")
        require_no_model_scores(result)
        with self.lock, self.connection() as con:
            if con.execute("UPDATE runs SET status=?,result=?,completed=? WHERE id=? AND status='running'",
                           (status, json.dumps(result, ensure_ascii=False, allow_nan=False), time.time(), rid)).rowcount != 1:
                raise ContractError("run_already_terminal")

    def private_medical_audit(self, rid, value):
        return self._private_audit(rid, value, "medical")

    def private_coordinator_audit(self, rid, value):
        return self._private_audit(rid, value, "coordinator")

    def _private_audit(self, rid, value, category):
        value = audit_value(value)
        folder = self.root / ("private-" + category + "-audit") / rid
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        ref = category + "-audit-" + uuid.uuid4().hex
        path = folder / (ref + ".json")
        temporary = path.with_suffix(".pending")
        with temporary.open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(path)
        path.chmod(0o600)
        return {"audit_ref": ref, "audit_sha256": digest(value)}
