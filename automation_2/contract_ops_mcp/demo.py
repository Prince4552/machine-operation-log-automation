from __future__ import annotations

import hashlib
from pathlib import Path
from random import Random

from .adapters.mock import MockAuditStore, MockContractSystem, MockDocumentStore, MockPartnerDirectory, MockWorkflowSystem
from .models import Contract, Document, Partner
from .policy import PolicyEngine
from .service import ContractOperationsService
from .store import SQLiteStore


def build_demo_service(db_path: Path, policy_path: Path, reset: bool = False) -> ContractOperationsService:
    store = SQLiteStore(db_path)
    if reset:
        store.reset()
    count = store.conn.execute("SELECT COUNT(*) AS n FROM partners").fetchone()["n"]
    if count == 0:
        _seed(store)
    policy = PolicyEngine(policy_path)
    return ContractOperationsService(
        store,
        MockPartnerDirectory(store),
        MockContractSystem(store),
        MockDocumentStore(store),
        MockWorkflowSystem(store),
        MockAuditStore(store),
        policy,
    )


def _seed(store: SQLiteStore, n_partners: int = 1000) -> None:
    rng = Random(42)
    partners: list[Partner] = []
    contracts: list[Contract] = []
    documents: list[Document] = []

    for i in range(1, n_partners + 1):
        partner_id = f"BP-{i:06d}"
        legal = f"{['Northwind', 'BlueRiver', 'Apex', 'Sakura', 'Orbit'][i % 5]} Supplier {i:05d}"
        tax = f"TX-{i:010d}"
        reg = f"REG-{i:08d}"
        partner = Partner(partner_id, legal, legal, "JP", tax, reg, "ACTIVE", rng.choice(["JPY", "USD", "EUR"]))
        partners.append(partner)
        doc_id = f"DOC-{i:08d}"
        digest = hashlib.sha256(f"{partner_id}|msa".encode()).hexdigest()
        documents.append(Document(doc_id, partner_id, f"{legal} MSA.pdf", "MSA", "ACTIVE", digest))

        contract_count = 2 if i % 4 == 0 else 1
        for j in range(1, contract_count + 1):
            contract_id = f"CON-{i:06d}-{j:02d}"
            open_obligations = 2 if (i % 17 == 0 and j == 1) else 0
            status = "ACTIVE" if j == 1 else "EXPIRED"
            contracts.append(
                Contract(
                    contract_id=contract_id,
                    partner_id=partner_id,
                    title=f"{legal} Services Agreement {j}",
                    status=status,
                    start_date="2026-01-01",
                    end_date="2027-12-31",
                    currency=partner.currency,
                    annual_value=float(100_000 + i * 750 + j * 10_000),
                    owner=f"owner{i % 25 + 1:02d}",
                    document_id=doc_id,
                    open_obligations=open_obligations,
                )
            )

    store.seed(partners, contracts, documents)


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    svc = build_demo_service(base / "data" / "contract_ops.db", base / "config" / "policy.json", reset=True)
    print(svc.search_partners("Northwind", 5))
