from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class RequestType(str, Enum):
    SUPPLIER_REGISTRATION = "supplier_registration"
    CONTRACT_CREATION = "contract_creation"
    CONTRACT_AMENDMENT = "contract_amendment"
    CONTRACT_TERMINATION = "contract_termination"


class CaseState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Partner:
    partner_id: str
    legal_name: str
    display_name: str
    country: str
    tax_id: str
    registration_id: str
    status: str
    currency: str


@dataclass(frozen=True)
class Contract:
    contract_id: str
    partner_id: str
    title: str
    status: str
    start_date: str
    end_date: str
    currency: str
    annual_value: float
    owner: str
    document_id: str
    open_obligations: int = 0


@dataclass(frozen=True)
class Document:
    document_id: str
    partner_id: str
    name: str
    document_type: str
    status: str
    content_hash: str


@dataclass(frozen=True)
class Evidence:
    source_system: str
    record_type: str
    record_id: str
    field: str
    value: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class Case:
    case_id: str
    request_type: RequestType
    state: CaseState
    partner_id: str | None
    contract_id: str | None
    requested_fields: dict[str, Any]
    findings: list[Finding]
    created_at: str
    updated_at: str
    created_by: str
    approved_by: str | None = None
    approval_reason: str | None = None
    submission_id: str | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "request_type": self.request_type.value,
            "state": self.state.value,
            "partner_id": self.partner_id,
            "contract_id": self.contract_id,
            "requested_fields": self.requested_fields,
            "findings": [f.to_dict() for f in self.findings],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approval_reason": self.approval_reason,
            "submission_id": self.submission_id,
            "idempotency_key": self.idempotency_key,
        }
