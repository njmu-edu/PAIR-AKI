"""Append-preserving run and event storage outside the code checkout."""
from __future__ import annotations
from pathlib import Path
from threading import RLock
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .domain import ContractError


class RunStore:
    def __init__(self, directory):
        self.root = Path(directory).expanduser().resolve()
        checkout = Path(__file__).resolve().parents[2]
        if self.root == checkout or checkout in self.root.parents:
            raise ContractError("runtime_state_must_be_outside_checkout")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "competition-runs.sqlite3"
        self.lock = RLock()
        with self.connection() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, status TEXT NOT NULL, request TEXT NOT NULL,
              result TEXT, created REAL NOT NULL, completed REAL);
            CREATE TABLE IF NOT EXISTS events (
              run_id TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL,
              PRIMARY KEY(run_id, seq));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def create(self, request):
        rid = "run-" + uuid.uuid4().hex
        with self.lock, self.connection() as con:
            con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                        (rid, "queued", json.dumps(request, ensure_ascii=False), None, time.time(), None))
        return rid

    def event(self, rid, event):
        with self.lock, self.connection() as con:
            row = con.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()
            if not row or row[0] in {"succeeded", "partial", "failed"}:
                raise ContractError("terminal_run_is_immutable")
            seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (rid,)).fetchone()[0]
            event = {**event, "seq": seq, "at": time.time()}
            con.execute("INSERT INTO events VALUES(?,?,?)", (rid, seq, json.dumps(event, ensure_ascii=False, allow_nan=False)))

    def start(self, rid):
        with self.lock, self.connection() as con:
            if con.execute("UPDATE runs SET status='running' WHERE id=? AND status='queued'", (rid,)).rowcount != 1:
                raise ContractError("run_not_queued")

    def finish(self, rid, status, result):
        if status not in {"succeeded", "partial", "failed"}:
            raise ContractError("terminal_status")
        with self.lock, self.connection() as con:
            changed = con.execute("UPDATE runs SET status=?,result=?,completed=? WHERE id=? AND status='running'",
                                  (status, json.dumps(result, ensure_ascii=False, allow_nan=False), time.time(), rid)).rowcount
            if changed != 1:
                raise ContractError("run_already_terminal")

    def read(self, rid):
        with self.connection() as con:
            r = con.execute("SELECT status,request,result,created,completed FROM runs WHERE id=?", (rid,)).fetchone()
            if not r:
                raise KeyError(rid)
            events = [json.loads(x[0]) for x in con.execute("SELECT event FROM events WHERE run_id=? ORDER BY seq", (rid,))]
        return {"run_id": rid, "status": r[0], "request": json.loads(r[1]),
                "result": json.loads(r[2]) if r[2] else None, "events": events,
                "created_at": r[3], "completed_at": r[4]}

    def recover_interrupted(self):
        """Only call after acquiring the service's exclusive state-directory lease."""
        with self.lock, self.connection() as con:
            rows = con.execute("SELECT id,status FROM runs WHERE status IN ('queued','running')").fetchall()
        for rid, status in rows:
            if status == "queued":
                self.start(rid)
            self.event(rid, {"kind": "recovery", "status": "failed", "reason": "previous_process_interrupted"})
            self.finish(rid, "failed", None)
