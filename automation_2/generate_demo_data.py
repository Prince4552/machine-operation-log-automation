from __future__ import annotations

import sqlite3
from pathlib import Path

from contract_ops_mcp.demo import build_demo_service

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "contract_ops.db"
POLICY = BASE / "config" / "policy.json"

if __name__ == "__main__":
    build_demo_service(DB, POLICY, reset=True)
    conn = sqlite3.connect(DB)
    partners = conn.execute("SELECT COUNT(*) FROM partners").fetchone()[0]
    contracts = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    print(f"Seeded demo database: partners={partners:,} contracts={contracts:,} documents={documents:,}")
