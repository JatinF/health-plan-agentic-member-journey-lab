"""Billing-review cases. Opening a case is a separate transition from requesting one."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from membercare.catalog import Actor
from membercare.errors import LabError


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CaseStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                member_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                eob_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                opened_at TEXT,
                rejected_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                tenant_id TEXT,
                actor_id TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                journey TEXT NOT NULL,
                result TEXT NOT NULL,
                narration TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                question TEXT NOT NULL
            );
            """
        )
        self._conn.commit()
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(turns)")}
        if "answer" not in columns:
            self._conn.execute("ALTER TABLE turns ADD COLUMN answer TEXT NOT NULL DEFAULT ''")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def audit(self, actor: Actor | None, action: str, result: str, detail: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (at, tenant_id, actor_id, action, result, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    None if actor is None else actor.tenant_id,
                    None if actor is None else actor.subject_id,
                    action,
                    result,
                    detail[:500],
                ),
            )
            self._conn.commit()

    def record_turn(self, row: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO turns (
                    at, thread_id, tenant_id, actor_id, channel, journey, result, narration, latency_ms, question, answer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    row["thread_id"],
                    row["tenant_id"],
                    row["actor_id"],
                    row["channel"],
                    row["journey"],
                    row["result"],
                    row["narration"],
                    row["latency_ms"],
                    row["question"][:500],
                    row.get("answer", "")[:2000],
                ),
            )
            self._conn.commit()

    def request(self, actor: Actor, eob_id: str, reason: str, thread_id: str) -> dict:
        self._require_member(actor)
        key = hashlib.sha256(f"{actor.tenant_id}|{actor.subject_id}|{eob_id}|{reason.strip()}".encode()).hexdigest()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT * FROM cases WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    self._conn.commit()
                    return _case_dict(existing)
                pending = self._conn.execute(
                    """
                    SELECT * FROM cases
                    WHERE tenant_id = ? AND member_id = ? AND status = 'pending_approval'
                    """,
                    (actor.tenant_id, actor.subject_id),
                ).fetchone()
                if pending is not None:
                    self._conn.commit()
                    return _case_dict(pending)
                case_id = self._next_id()
                self._conn.execute(
                    """
                    INSERT INTO cases (
                        id, tenant_id, member_id, patient_id, eob_id, reason, idempotency_key,
                        thread_id, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?)
                    """,
                    (
                        case_id,
                        actor.tenant_id,
                        actor.subject_id,
                        actor.patient_id,
                        eob_id,
                        reason.strip(),
                        key,
                        thread_id,
                        _now(),
                    ),
                )
                row = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
                self._conn.commit()
                return _case_dict(row)
            except Exception:
                self._conn.rollback()
                raise

    def approve(self, actor: Actor, case_id: str) -> dict:
        self._require_reviewer(actor)
        return self._transition(actor, case_id, "approve")

    def open_case(self, actor: Actor, case_id: str) -> dict:
        self._require_reviewer(actor)
        return self._transition(actor, case_id, "open")

    def reject(self, actor: Actor, case_id: str) -> dict:
        self._require_reviewer(actor)
        return self._transition(actor, case_id, "reject")

    def get(self, actor: Actor, case_id: str) -> dict:
        row = self._fetch(case_id)
        self._can_read(actor, row)
        return _case_dict(row)

    def list_cases(self, actor: Actor) -> list[dict]:
        with self._lock:
            if actor.role == "member":
                rows = self._conn.execute(
                    "SELECT * FROM cases WHERE tenant_id = ? AND member_id = ? ORDER BY id",
                    (actor.tenant_id, actor.subject_id),
                ).fetchall()
            elif actor.role == "reviewer":
                rows = self._conn.execute(
                    "SELECT * FROM cases WHERE tenant_id = ? ORDER BY id",
                    (actor.tenant_id,),
                ).fetchall()
            else:
                raise LabError("permission_denied", "role cannot list cases")
        return [_case_dict(row) for row in rows]

    def turn_for_actor(self, actor: Actor, thread_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT thread_id, channel, journey, result, narration, latency_ms, at, answer
                FROM turns
                WHERE thread_id = ? AND tenant_id = ? AND actor_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (thread_id, actor.tenant_id, actor.subject_id),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def pending_for_member(self, actor: Actor) -> dict | None:
        self._require_member(actor)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM cases
                WHERE tenant_id = ? AND member_id = ? AND status = 'pending_approval'
                ORDER BY id LIMIT 1
                """,
                (actor.tenant_id, actor.subject_id),
            ).fetchone()
        return None if row is None else _case_dict(row)

    def _transition(self, actor: Actor, case_id: str, action: str) -> dict:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
                if row is None or row["tenant_id"] != actor.tenant_id:
                    raise LabError("not_found", "case was not found")
                status = row["status"]
                if action == "approve":
                    if status == "pending_approval":
                        self._conn.execute(
                            "UPDATE cases SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
                            (actor.subject_id, _now(), case_id),
                        )
                    elif status not in {"approved", "open"}:
                        raise LabError("invalid", f"cannot approve a case that is {status}")
                elif action == "open":
                    if status == "approved":
                        self._conn.execute(
                            "UPDATE cases SET status = 'open', opened_at = ? WHERE id = ?",
                            (_now(), case_id),
                        )
                    elif status != "open":
                        raise LabError("approval_required", "a reviewer must approve the case before it opens")
                elif action == "reject":
                    if status == "pending_approval":
                        self._conn.execute(
                            "UPDATE cases SET status = 'rejected', rejected_at = ? WHERE id = ?",
                            (_now(), case_id),
                        )
                    elif status != "rejected":
                        raise LabError("invalid", f"cannot reject a case that is {status}")
                updated = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
                self._conn.commit()
                return _case_dict(updated)
            except Exception:
                self._conn.rollback()
                raise

    def _fetch(self, case_id: str) -> sqlite3.Row:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise LabError("not_found", "case was not found")
        return row

    def _next_id(self) -> str:
        row = self._conn.execute("SELECT value FROM counters WHERE name = 'case'").fetchone()
        value = 1 if row is None else int(row["value"]) + 1
        self._conn.execute(
            "INSERT INTO counters (name, value) VALUES ('case', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
            (value,),
        )
        return f"CASE-{value:04d}"

    def _can_read(self, actor: Actor, row: sqlite3.Row) -> None:
        if row["tenant_id"] != actor.tenant_id:
            raise LabError("not_found", "case was not found")
        if actor.role == "member" and row["member_id"] != actor.subject_id:
            raise LabError("not_found", "case was not found")
        if actor.role not in {"member", "reviewer"}:
            raise LabError("permission_denied", "role cannot read cases")

    @staticmethod
    def _require_member(actor: Actor) -> None:
        if actor.role != "member" or not actor.patient_id:
            raise LabError("permission_denied", "a member actor is required")

    @staticmethod
    def _require_reviewer(actor: Actor) -> None:
        if actor.role != "reviewer":
            raise LabError("permission_denied", "a reviewer actor is required")


def _case_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}
