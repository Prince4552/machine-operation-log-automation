from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from threading import Lock, local
from typing import Any

from .models import Case, CaseState, Contract, Document, Partner, RequestType, Evidence, Finding, Severity


class SQLiteStore:
    """Small durable demo store. In production, this can be replaced with Postgres or a managed service."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # MCP tool handlers are executed in worker threads by the SDK. A single
        # SQLite connection cannot safely be shared across those threads.
        # Keep one connection per thread instead of sharing the connection that
        # was created when the server module was imported.
        self._local = local()
        self._schema_lock = Lock()
        with self._schema_lock:
            connection = self.conn
            connection.execute("PRAGMA journal_mode=WAL")
            self._create_schema(connection)

    @property
    def conn(self) -> sqlite3.Connection:
        connection = getattr(self._local, "conn", None)
        if connection is None:
            connection = self._new_connection()
            self._local.conn = connection
        return connection

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "conn", None)
        if connection is not None:
            try:
                connection.close()
            finally:
                self._local.conn = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        c = connection.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS partners (
                partner_id TEXT PRIMARY KEY,
                legal_name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                country TEXT NOT NULL,
                tax_id TEXT NOT NULL,
                registration_id TEXT NOT NULL,
                status TEXT NOT NULL,
                currency TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contracts (
                contract_id TEXT PRIMARY KEY,
                partner_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                currency TEXT NOT NULL,
                annual_value REAL NOT NULL,
                owner TEXT NOT NULL,
                document_id TEXT NOT NULL,
                open_obligations INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                partner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                status TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                submission_id TEXT,
                idempotency_key TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                case_id TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT NOT NULL
            );
            """
        )
        connection.commit()

    def reset(self) -> None:
        self.conn.executescript("DELETE FROM partners; DELETE FROM contracts; DELETE FROM documents; DELETE FROM cases; DELETE FROM audit;")
        self.conn.commit()

    def seed(self, partners: list[Partner], contracts: list[Contract], documents: list[Document]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO partners VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(asdict(p).values()) for p in partners],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(asdict(c).values()) for c in contracts],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?)",
            [tuple(asdict(d).values()) for d in documents],
        )
        self.conn.commit()

    def search_partners(self, query: str, limit: int) -> list[Partner]:
        q = f"%{query.strip().lower()}%"
        rows = self.conn.execute(
            "SELECT * FROM partners WHERE lower(legal_name) LIKE ? OR lower(display_name) LIKE ? OR lower(tax_id) LIKE ? LIMIT ?",
            (q, q, q, limit),
        ).fetchall()
        return [Partner(**dict(r)) for r in rows]

    def get_partner(self, partner_id: str) -> Partner | None:
        row = self.conn.execute("SELECT * FROM partners WHERE partner_id=?", (partner_id,)).fetchone()
        return Partner(**dict(row)) if row else None

    def find_duplicates(self, legal_name: str, tax_id: str | None, registration_id: str | None, limit: int) -> list[Partner]:
        rows = self.conn.execute(
            """
            SELECT * FROM partners
            WHERE (? != '' AND lower(legal_name)=lower(?))
               OR (? IS NOT NULL AND ? != '' AND tax_id=?)
               OR (? IS NOT NULL AND ? != '' AND registration_id=?)
            LIMIT ?
            """,
            (legal_name, legal_name, tax_id, tax_id, tax_id, registration_id, registration_id, registration_id, limit),
        ).fetchall()
        return [Partner(**dict(r)) for r in rows]

    def list_contracts(self, partner_id: str, status: str | None = None) -> list[Contract]:
        if status:
            rows = self.conn.execute("SELECT * FROM contracts WHERE partner_id=? AND status=?", (partner_id, status)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM contracts WHERE partner_id=?", (partner_id,)).fetchall()
        return [Contract(**dict(r)) for r in rows]

    def get_contract(self, contract_id: str) -> Contract | None:
        row = self.conn.execute("SELECT * FROM contracts WHERE contract_id=?", (contract_id,)).fetchone()
        return Contract(**dict(row)) if row else None

    def list_documents(self, partner_id: str) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents WHERE partner_id=?", (partner_id,)).fetchall()
        return [Document(**dict(r)) for r in rows]

    def save_case(self, case: Case) -> None:
        payload = json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            "INSERT OR REPLACE INTO cases(case_id,payload,state,submission_id,idempotency_key) VALUES (?,?,?,?,?)",
            (case.case_id, payload, case.state.value, case.submission_id, case.idempotency_key),
        )
        self.conn.commit()

    def get_case(self, case_id: str) -> Case | None:
        row = self.conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            return None
        p = json.loads(row["payload"])
        findings = []
        for f in p["findings"]:
            ev = tuple(Evidence(**e) for e in f.get("evidence", []))
            findings.append(Finding(f["code"], Severity(f["severity"]), f["message"], ev))
        return Case(
            case_id=p["case_id"], request_type=RequestType(p["request_type"]), state=CaseState(p["state"]),
            partner_id=p["partner_id"], contract_id=p["contract_id"], requested_fields=p["requested_fields"],
            findings=findings, created_at=p["created_at"], updated_at=p["updated_at"], created_by=p["created_by"],
            approved_by=p.get("approved_by"), approval_reason=p.get("approval_reason"),
            submission_id=p.get("submission_id"), idempotency_key=p.get("idempotency_key")
        )

    def find_case_by_idempotency(self, key: str) -> Case | None:
        row = self.conn.execute("SELECT case_id FROM cases WHERE idempotency_key=?", (key,)).fetchone()
        return self.get_case(row["case_id"]) if row else None

    def audit(self, ts: str, case_id: str, event: str, details: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO audit(ts,case_id,event,details) VALUES (?,?,?,?)", (ts, case_id, event, json.dumps(details, ensure_ascii=False, sort_keys=True)))
        self.conn.commit()

    def audit_events(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT ts, event, details FROM audit WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
        return [{"timestamp": r["ts"], "event": r["event"], "details": json.loads(r["details"])} for r in rows]
