from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from ..demo import build_demo_service

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("CONTRACT_OPS_DB", BASE_DIR / "data" / "contract_ops.db"))
POLICY_PATH = Path(os.getenv("CONTRACT_OPS_POLICY", BASE_DIR / "config" / "policy.json"))

service = build_demo_service(DB_PATH, POLICY_PATH, reset=False)
mcp = MCPServer(
    "supplier-contract-operations",
    instructions=(
        "Enterprise supplier and contract operations tools. "
        "Use read tools to gather facts, policy tools to validate a requested action, "
        "prepare_case to create a reviewable case, and never submit without explicit approval."
    ),
)


@mcp.tool()
def search_business_partners(query: str, limit: int = 10) -> dict[str, Any]:
    """Search the supplier/partner master for likely matching records."""
    return service.search_partners(query, limit)


@mcp.tool()
def get_business_partner(partner_id: str) -> dict[str, Any]:
    """Return a partner profile plus linked contracts and controlled documents."""
    return service.get_partner(partner_id)


@mcp.tool()
def list_partner_contracts(partner_id: str, status: str | None = None) -> dict[str, Any]:
    """List contracts for a partner, optionally filtered by status."""
    return service.list_contracts(partner_id, status)


@mcp.tool()
def get_contract(contract_id: str) -> dict[str, Any]:
    """Return a single contract record and its current lifecycle data."""
    return service.get_contract(contract_id)


@mcp.tool()
def check_request_completeness(request_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Check whether a proposed supplier/contract request contains required information."""
    return service.check_completeness(request_type, fields)


@mcp.tool()
def find_duplicate_candidates(
    legal_name: str,
    tax_id: str | None = None,
    registration_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find possible duplicate supplier records before creating a new partner."""
    return service.find_duplicates(legal_name, tax_id, registration_id, limit)


@mcp.tool()
def assess_contract_request(
    request_type: str,
    partner_id: str | None = None,
    contract_id: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic policy and data checks and explain why the request is blocked or needs review."""
    return service.assess_request(request_type, partner_id, contract_id, fields or {})


@mcp.tool()
def prepare_contract_case(
    request_type: str,
    partner_id: str | None,
    contract_id: str | None,
    fields: dict[str, Any],
    justification: str,
    requested_by: str,
) -> dict[str, Any]:
    """Create a durable, reviewable case from a validated request. Hard failures produce BLOCKED."""
    return service.prepare_request(request_type, partner_id, contract_id, fields, justification, requested_by)


@mcp.tool()
def request_human_approval(case_id: str) -> dict[str, Any]:
    """Move a clean draft case into PENDING_APPROVAL."""
    return service.request_approval(case_id)


@mcp.tool()
def approve_case(case_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    """Approve a case after a human review. Production deployments should derive reviewer identity from SSO/OAuth, not from model text."""
    return service.approve_case(case_id, reviewer, reason)


@mcp.tool()
def submit_case(case_id: str) -> dict[str, Any]:
    """Submit an approved case through the configured integration. Demo mode is idempotent and mocked."""
    return service.submit_case(case_id)


@mcp.tool()
def get_case(case_id: str) -> dict[str, Any]:
    """Return case state, findings, and the audit trail."""
    return service.get_case(case_id)


@mcp.resource("contract-ops://policy")
def policy_resource() -> str:
    """Return the active policy used by deterministic validation and risk checks."""
    return json.dumps(service.policy.config, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
