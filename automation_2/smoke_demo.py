from __future__ import annotations

from pathlib import Path
import json

from contract_ops_mcp.demo import build_demo_service
from contract_ops_mcp.models import RequestType

BASE = Path(__file__).resolve().parent
service = build_demo_service(BASE / "data" / "contract_ops.db", BASE / "config" / "policy.json", reset=True)

print("=== Supplier search ===")
print(json.dumps(service.search_partners("Northwind", 3), indent=2, ensure_ascii=False))

print("\n=== Contract termination safety check ===")
assessment = service.assess_request(
    RequestType.CONTRACT_TERMINATION.value,
    "BP-000017",
    "CON-000017-01",
    {
        "termination_reason": "End of engagement",
        "requested_end_date": "2026-12-01",
        "confirmation_no_open_obligations": True,
    },
)
print(json.dumps(assessment, indent=2, ensure_ascii=False))

print("\n=== Safe supplier-registration case ===")
case = service.prepare_request(
    RequestType.SUPPLIER_REGISTRATION.value,
    None,
    None,
    {
        "legal_name": "Fresh Supplier Ltd",
        "tax_id": "TX-FRESH-001",
        "registration_id": "REG-FRESH-001",
        "country": "JP",
        "currency": "JPY",
        "source_reference": "DEMO-REQ-001",
    },
    "Register approved new supplier",
    "demo-operator",
)
print(f"case={case['case_id']} state={case['state']}")
case = service.request_approval(case["case_id"])
case = service.approve_case(case["case_id"], "demo-reviewer", "Reviewed supplier data and findings")
case = service.submit_case(case["case_id"])
print(f"state={case['state']} submission={case['submission_id']}")
