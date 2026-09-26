from __future__ import annotations

from typing import Any

from ..models import Contract, Document, Partner
from ..ports import AuditStore, ContractSystem, DocumentStore, PartnerDirectory, WorkflowSystem
from ..store import SQLiteStore


class MockPartnerDirectory(PartnerDirectory):
    def __init__(self, store: SQLiteStore):
        self.store = store

    def search(self, query: str, limit: int = 10) -> list[Partner]:
        return self.store.search_partners(query, limit)

    def get(self, partner_id: str) -> Partner | None:
        return self.store.get_partner(partner_id)

    def find_duplicates(self, legal_name: str, tax_id: str | None = None, registration_id: str | None = None, limit: int = 10) -> list[Partner]:
        return self.store.find_duplicates(legal_name, tax_id, registration_id, limit)


class MockContractSystem(ContractSystem):
    def __init__(self, store: SQLiteStore):
        self.store = store

    def list_for_partner(self, partner_id: str, status: str | None = None) -> list[Contract]:
        return self.store.list_contracts(partner_id, status)

    def get(self, contract_id: str) -> Contract | None:
        return self.store.get_contract(contract_id)


class MockDocumentStore(DocumentStore):
    def __init__(self, store: SQLiteStore):
        self.store = store

    def list_for_partner(self, partner_id: str) -> list[Document]:
        return self.store.list_documents(partner_id)


class MockWorkflowSystem(WorkflowSystem):
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_case(self, case: dict[str, Any]) -> str:
        return case["case_id"]

    def submit_case(self, case: dict[str, Any], idempotency_key: str) -> str:
        existing = self.store.find_case_by_idempotency(idempotency_key)
        if existing and existing.submission_id:
            return existing.submission_id
        return "SUB-" + idempotency_key[:16].upper()


class MockAuditStore(AuditStore):
    def __init__(self, store: SQLiteStore):
        self.store = store

    def record(self, event: str, case_id: str, details: dict[str, Any]) -> None:
        from ..service import utc_now
        self.store.audit(utc_now(), case_id, event, details)
