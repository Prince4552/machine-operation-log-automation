from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Case, CaseState, Contract, Evidence, Finding, Partner, RequestType, Severity
from .policy import PolicyEngine
from .ports import AuditStore, ContractSystem, DocumentStore, PartnerDirectory, WorkflowSystem
from .store import SQLiteStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, payload: dict[str, Any], length: int = 16) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:length].upper()}"


def normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


class ContractOperationsService:
    def __init__(
        self,
        store: SQLiteStore,
        partner_directory: PartnerDirectory,
        contract_system: ContractSystem,
        document_store: DocumentStore,
        workflow_system: WorkflowSystem,
        audit_store: AuditStore,
        policy: PolicyEngine,
    ) -> None:
        self.store = store
        self.partners = partner_directory
        self.contracts = contract_system
        self.documents = document_store
        self.workflow = workflow_system
        self.audit = audit_store
        self.policy = policy

    def search_partners(self, query: str, limit: int = 10) -> dict[str, Any]:
        query = normalize_query(query)
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        rows = [asdict(p) for p in self.partners.search(query, limit)]
        return {"count": len(rows), "partners": rows}

    def get_partner(self, partner_id: str) -> dict[str, Any]:
        p = self.partners.get(partner_id)
        if not p:
            return {"found": False, "partner_id": partner_id}
        contracts = [asdict(c) for c in self.contracts.list_for_partner(partner_id)]
        docs = [asdict(d) for d in self.documents.list_for_partner(partner_id)]
        return {"found": True, "partner": asdict(p), "contracts": contracts, "documents": docs}

    def get_contract(self, contract_id: str) -> dict[str, Any]:
        c = self.contracts.get(contract_id)
        if not c:
            return {"found": False, "contract_id": contract_id}
        return {"found": True, "contract": asdict(c)}

    def list_contracts(self, partner_id: str, status: str | None = None) -> dict[str, Any]:
        if not self.partners.get(partner_id):
            return {"found": False, "partner_id": partner_id, "contracts": []}
        rows = [asdict(c) for c in self.contracts.list_for_partner(partner_id, status)]
        return {"found": True, "count": len(rows), "contracts": rows}

    def check_completeness(
        self,
        request_type: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        rt = RequestType(request_type)
        required = self.policy.required_fields(rt)
        missing = [key for key in required if not fields.get(key)]
        return {
            "request_type": rt.value,
            "required_fields": required,
            "provided_fields": sorted([k for k, v in fields.items() if v not in (None, "")]),
            "missing_fields": missing,
            "complete": not missing,
        }

    def find_duplicates(
        self,
        legal_name: str,
        tax_id: str | None = None,
        registration_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if not normalize_query(legal_name):
            raise ValueError("legal_name must not be empty")
        if not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        matches = [asdict(p) for p in self.partners.find_duplicates(legal_name, tax_id, registration_id, limit)]
        return {"count": len(matches), "matches": matches}

    def assess_request(
        self,
        request_type: str,
        partner_id: str | None,
        contract_id: str | None,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        rt = RequestType(request_type)
        partner = self.partners.get(partner_id) if partner_id else None
        contract = self.contracts.get(contract_id) if contract_id else None
        duplicates = []
        if rt == RequestType.SUPPLIER_REGISTRATION:
            duplicates = self.partners.find_duplicates(
                fields.get("legal_name", ""), fields.get("tax_id"), fields.get("registration_id"), 10
            )
        findings = self.policy.validate_request(rt, partner, contract, fields, len(duplicates))
        if contract_id and not contract:
            findings.append(Finding("CONTRACT_NOT_FOUND", Severity.CRITICAL, f"Contract {contract_id} was not found."))
        if partner_id and not partner:
            findings.append(Finding("PARTNER_NOT_FOUND", Severity.CRITICAL, f"Partner {partner_id} was not found."))
        if rt in {RequestType.CONTRACT_CREATION, RequestType.CONTRACT_AMENDMENT, RequestType.CONTRACT_TERMINATION} and not partner_id and rt == RequestType.CONTRACT_CREATION:
            findings.append(Finding("PARTNER_REQUIRED", Severity.CRITICAL, "partner_id is required for contract creation."))
        if rt in {RequestType.CONTRACT_AMENDMENT, RequestType.CONTRACT_TERMINATION} and not contract_id:
            findings.append(Finding("CONTRACT_REQUIRED", Severity.CRITICAL, "contract_id is required for this request type."))
        return {
            "request_type": rt.value,
            "blocking": self.policy.blocks(findings),
            "enhanced_review": self.policy.needs_enhanced_review(findings),
            "findings": [f.to_dict() for f in findings],
            "duplicate_candidates": [asdict(p) for p in duplicates],
        }

    def prepare_request(
        self,
        request_type: str,
        partner_id: str | None,
        contract_id: str | None,
        fields: dict[str, Any],
        justification: str,
        requested_by: str,
    ) -> dict[str, Any]:
        rt = RequestType(request_type)
        if not requested_by.strip():
            raise ValueError("requested_by is required")
        if not justification.strip():
            raise ValueError("justification is required")
        assessment = self.assess_request(rt.value, partner_id, contract_id, fields)
        findings = [self._finding_from_dict(x) for x in assessment["findings"]]
        payload = {
            "request_type": rt.value,
            "partner_id": partner_id,
            "contract_id": contract_id,
            "fields": fields,
            "justification": justification.strip(),
            "requested_by": requested_by.strip(),
        }
        case_id = stable_id("CASE", payload)
        idempotency_key = stable_id("IDEMP", payload, 24)
        now = utc_now()
        state = CaseState.BLOCKED if assessment["blocking"] else CaseState.DRAFT
        case = Case(
            case_id=case_id,
            request_type=rt,
            state=state,
            partner_id=partner_id,
            contract_id=contract_id,
            requested_fields=fields,
            findings=findings,
            created_at=now,
            updated_at=now,
            created_by=requested_by.strip(),
            idempotency_key=idempotency_key,
        )
        self.store.save_case(case)
        self.audit.record("CASE_CREATED", case_id, {"state": state.value, "request_type": rt.value})
        return case.to_dict()

    def request_approval(self, case_id: str) -> dict[str, Any]:
        case = self._required_case(case_id)
        if case.state == CaseState.PENDING_APPROVAL:
            return case.to_dict()
        if case.state != CaseState.DRAFT:
            raise ValueError(f"Cannot request approval from {case.state.value}")
        if self.policy.blocks(case.findings):
            raise ValueError("Blocked case cannot enter approval")
        case.state = CaseState.PENDING_APPROVAL
        case.updated_at = utc_now()
        self.store.save_case(case)
        self.audit.record("APPROVAL_REQUESTED", case_id, {})
        return case.to_dict()

    def approve_case(self, case_id: str, reviewer: str, reason: str) -> dict[str, Any]:
        case = self._required_case(case_id)
        if case.state == CaseState.APPROVED:
            return case.to_dict()
        if case.state != CaseState.PENDING_APPROVAL:
            raise ValueError(f"Cannot approve from {case.state.value}")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("reviewer and reason are required")
        if self.policy.blocks(case.findings):
            raise ValueError("Blocked case cannot be approved")
        case.state = CaseState.APPROVED
        case.approved_by = reviewer.strip()
        case.approval_reason = reason.strip()
        case.updated_at = utc_now()
        self.store.save_case(case)
        self.audit.record("CASE_APPROVED", case_id, {"reviewer": case.approved_by})
        return case.to_dict()

    def submit_case(self, case_id: str) -> dict[str, Any]:
        case = self._required_case(case_id)
        if case.state == CaseState.SUBMITTED:
            return case.to_dict()
        if case.state != CaseState.APPROVED:
            raise ValueError(f"Cannot submit from {case.state.value}")
        submission_id = self.workflow.submit_case(case.to_dict(), case.idempotency_key or case.case_id)
        case.state = CaseState.SUBMITTED
        case.submission_id = submission_id
        case.updated_at = utc_now()
        self.store.save_case(case)
        self.audit.record("CASE_SUBMITTED", case_id, {"submission_id": submission_id, "mode": "MOCK"})
        return case.to_dict()

    def get_case(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if not case:
            return {"found": False, "case_id": case_id}
        return {"found": True, "case": case.to_dict(), "audit": self.store.audit_events(case_id)}

    def _required_case(self, case_id: str) -> Case:
        case = self.store.get_case(case_id)
        if not case:
            raise ValueError(f"Unknown case: {case_id}")
        return case

    @staticmethod
    def _finding_from_dict(data: dict[str, Any]) -> Finding:
        return Finding(data["code"], Severity(data["severity"]), data["message"], tuple())
