from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import Contract, Document, Partner


class PartnerDirectory(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[Partner]: ...

    @abstractmethod
    def get(self, partner_id: str) -> Partner | None: ...

    @abstractmethod
    def find_duplicates(self, legal_name: str, tax_id: str | None = None, registration_id: str | None = None, limit: int = 10) -> list[Partner]: ...


class ContractSystem(ABC):
    @abstractmethod
    def list_for_partner(self, partner_id: str, status: str | None = None) -> list[Contract]: ...

    @abstractmethod
    def get(self, contract_id: str) -> Contract | None: ...


class DocumentStore(ABC):
    @abstractmethod
    def list_for_partner(self, partner_id: str) -> list[Document]: ...


class WorkflowSystem(ABC):
    @abstractmethod
    def create_case(self, case: dict[str, Any]) -> str: ...

    @abstractmethod
    def submit_case(self, case: dict[str, Any], idempotency_key: str) -> str: ...


class AuditStore(ABC):
    @abstractmethod
    def record(self, event: str, case_id: str, details: dict[str, Any]) -> None: ...
