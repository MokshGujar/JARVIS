from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config import BASE_DIR


SCHEMA_VERSION = 1
DEFAULT_DB_PATH = Path(BASE_DIR) / "database" / "runtime_state.sqlite3"


class RuntimeStateStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._initialized = False

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def ensure_schema(self) -> None:
        with self._lock:
            if self._initialized:
                return
            existed = self.db_path.exists()
            with self.connect() as connection:
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if existed and user_version < SCHEMA_VERSION:
                    self._backup_existing_db()
                self._create_schema(connection)
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.commit()
            self._initialized = True

    def record_session(self, session_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        self.ensure_schema()
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(session_id, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (session_id, now, now, _json(metadata or {})),
            )
            connection.commit()

    def record_turn(self, session_id: str, turn_id: str, *, status: str = "started", metadata: dict[str, Any] | None = None) -> None:
        self.ensure_schema()
        self.record_session(session_id)
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO turns(turn_id, session_id, status, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
                """,
                (turn_id, session_id, status, now, now, _json(metadata or {})),
            )
            connection.commit()

    def record_policy_decision(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        tool_name: str,
        action: str,
        decision: str,
        risk_level: str,
        requires_confirmation: bool,
        requires_step_up: bool,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self.ensure_schema()
        self._ensure_optional_session_turn(session_id, turn_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO policy_decisions(
                    session_id, turn_id, tool_name, action, decision, risk_level,
                    requires_confirmation, requires_step_up, reason, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    tool_name,
                    action,
                    decision,
                    risk_level,
                    int(requires_confirmation),
                    int(requires_step_up),
                    reason,
                    _json(metadata or {}),
                    _now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def record_execution_event(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        tool_name: str,
        action: str,
        result: str,
        ok: bool,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self.ensure_schema()
        self._ensure_optional_session_turn(session_id, turn_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO execution_events(
                    session_id, turn_id, tool_name, action, result, ok, error, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, turn_id, tool_name, action, result, int(ok), error, _json(metadata or {}), _now()),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def record_audit_event(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        event_type: str,
        intent_action: str,
        plan_summary: str,
        policy_decision: str,
        tool_name: str,
        execution_result: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self.ensure_schema()
        self._ensure_optional_session_turn(session_id, turn_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events(
                    session_id, turn_id, event_type, intent_action, plan_summary,
                    policy_decision, tool_name, execution_result, error, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    event_type,
                    intent_action,
                    plan_summary,
                    policy_decision,
                    tool_name,
                    execution_result,
                    error,
                    _json(metadata or {}),
                    _now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def create_pending_confirmation(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        tool_name: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_schema()
        self._ensure_optional_session_turn(session_id, turn_id)
        confirmation_id = f"confirm-{uuid.uuid4().hex}"
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO confirmations(
                    confirmation_id, session_id, turn_id, tool_name, action,
                    status, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (confirmation_id, session_id, turn_id, tool_name, action, now, now, _json(metadata or {})),
            )
            connection.commit()
        return confirmation_id

    def get_pending_confirmation(self, *, session_id: str | None, turn_id: str | None = None) -> dict[str, Any] | None:
        self.ensure_schema()
        self.expire_pending_confirmations()
        clauses = ["status='pending'"]
        values: list[Any] = []
        if session_id is not None:
            clauses.append("session_id=?")
            values.append(session_id)
        if turn_id is not None:
            clauses.append("turn_id=?")
            values.append(turn_id)
        query = f"SELECT * FROM confirmations WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 1"
        with self.connect() as connection:
            row = connection.execute(query, values).fetchone()
        return _row_dict(row) if row is not None else None

    def get_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM confirmations WHERE confirmation_id=?", (confirmation_id,)).fetchone()
        return _row_dict(row) if row is not None else None

    def accept_confirmation(self, confirmation_id: str) -> None:
        self.resolve_confirmation(confirmation_id, status="accepted")

    def cancel_confirmation(self, confirmation_id: str) -> None:
        self.resolve_confirmation(confirmation_id, status="cancelled")

    def expire_confirmation(self, confirmation_id: str) -> None:
        self.resolve_confirmation(confirmation_id, status="expired")

    def expire_pending_confirmations(self) -> int:
        self.ensure_schema()
        now = time.time()
        expired_ids: list[str] = []
        with self.connect() as connection:
            rows = connection.execute("SELECT confirmation_id, metadata_json FROM confirmations WHERE status='pending'").fetchall()
            for row in rows:
                metadata = _loads_json(row["metadata_json"])
                expires_at = metadata.get("expires_at")
                try:
                    should_expire = expires_at is not None and float(expires_at) <= now
                except Exception:
                    should_expire = False
                if should_expire:
                    expired_ids.append(str(row["confirmation_id"]))
            if expired_ids:
                connection.executemany(
                    "UPDATE confirmations SET status='expired', updated_at=? WHERE confirmation_id=? AND status='pending'",
                    [(_now(), confirmation_id) for confirmation_id in expired_ids],
                )
                connection.commit()
        return len(expired_ids)

    def resolve_confirmation(self, confirmation_id: str, *, status: str) -> None:
        normalized = str(status or "").strip().lower()
        if normalized not in {"accepted", "cancelled", "expired"}:
            raise ValueError("confirmation status must be accepted, cancelled, or expired")
        self.ensure_schema()
        with self.connect() as connection:
            connection.execute(
                "UPDATE confirmations SET status=?, updated_at=? WHERE confirmation_id=? AND status='pending'",
                (normalized, _now(), confirmation_id),
            )
            connection.commit()

    def _ensure_optional_session_turn(self, session_id: str | None, turn_id: str | None) -> None:
        if session_id:
            self.record_session(session_id)
        if session_id and turn_id:
            self.record_turn(session_id, turn_id)

    def _backup_existing_db(self) -> None:
        if not self.db_path.exists():
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_suffix(f".pre_schema_{timestamp}.sqlite3.bak")
        shutil.copy2(self.db_path, backup_path)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS policy_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                decision TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                requires_confirmation INTEGER NOT NULL,
                requires_step_up INTEGER NOT NULL,
                reason TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS confirmations (
                confirmation_id TEXT PRIMARY KEY,
                session_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS execution_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_id TEXT,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                ok INTEGER NOT NULL,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_id TEXT,
                event_type TEXT NOT NULL,
                intent_action TEXT NOT NULL,
                plan_summary TEXT NOT NULL,
                policy_decision TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                execution_result TEXT NOT NULL,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE SET NULL
            );
            """
        )


_default_store: RuntimeStateStore | None = None


def get_runtime_state_store() -> RuntimeStateStore:
    global _default_store
    if _default_store is None:
        _default_store = RuntimeStateStore()
    return _default_store


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    metadata = result.get("metadata_json")
    if isinstance(metadata, str):
        result["metadata"] = _loads_json(metadata)
    return result


def _loads_json(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}
