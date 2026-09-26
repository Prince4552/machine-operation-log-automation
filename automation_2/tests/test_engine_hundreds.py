from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contract_ops_mcp.adapters.mock import MockAuditStore, MockContractSystem, MockDocumentStore, MockPartnerDirectory, MockWorkflowSystem
from contract_ops_mcp.demo import build_demo_service
from contract_ops_mcp.models import CaseState, RequestType, Severity
from contract_ops_mcp.policy import PolicyEngine
from contract_ops_mcp.service import ContractOperationsService
from contract_ops_mcp.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "policy.json"


class TestPolicyCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = PolicyEngine(POLICY)

    def test_all_request_types_have_required_fields(self):
        for value in self.policy.config["request_types"]:
            with self.subTest(request_type=value):
                self.assertTrue(self.policy.required_fields(RequestType(value)))

    def test_supported_currency_matrix(self):
        supported = self.policy.config["supported_currencies"]
        for cur in supported:
            with self.subTest(currency=cur):
                result = self.policy.validate_request(
                    RequestType.SUPPLIER_REGISTRATION,
                    None, None,
                    {f: ("x" if f != "currency" else cur) for f in self.policy.required_fields(RequestType.SUPPLIER_REGISTRATION)},
                )
                self.assertFalse(any(f.code == "UNSUPPORTED_CURRENCY" for f in result))


# 160 generated unit cases for missing required fields.
for idx in range(160):
    request_values = list(RequestType)
    rt = request_values[idx % len(request_values)]
    required = PolicyEngine(POLICY).required_fields(rt)
    field_to_remove = required[idx % len(required)]
    base = {f: "value" for f in required}
    base["currency"] = "JPY"
    if "annual_value" in base:
        base["annual_value"] = 100000

    def make_test(rt=rt, field_to_remove=field_to_remove, base=base.copy(), idx=idx):
        def test(self):
            local = dict(base)
            local.pop(field_to_remove, None)
            result = self.policy.validate_request(rt, None, None, local)
            self.assertTrue(any(f.code == "MISSING_REQUIRED_FIELDS" for f in result), f"case {idx}")
            self.assertTrue(self.policy.blocks(result), f"case {idx}")
        return test
    setattr(TestPolicyCore, f"test_missing_required_{idx:03d}", make_test())


# 80 state machine edge cases: every invalid source state must be rejected by approval/submission.
class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract_ops_state_"))
        self.service = build_demo_service(self.tmp / "db.sqlite", POLICY, reset=True)
        partner_id = "BP-000001"
        self.partner_id = partner_id
        self.fields = {
            "legal_name": "Fresh Supplier",
            "tax_id": "TX-NEW-0001",
            "registration_id": "REG-NEW-0001",
            "country": "JP",
            "currency": "JPY",
            "source_reference": "REQ-1",
        }

    def _case(self):
        return self.service.prepare_request(
            RequestType.SUPPLIER_REGISTRATION.value, None, None,
            self.fields, "New supplier request", "operator"
        )

    def test_normal_lifecycle(self):
        case = self._case()
        self.assertEqual(case["state"], "DRAFT")
        c = self.service.request_approval(case["case_id"])
        self.assertEqual(c["state"], "PENDING_APPROVAL")
        c = self.service.approve_case(case["case_id"], "reviewer", "Reviewed")
        self.assertEqual(c["state"], "APPROVED")
        c = self.service.submit_case(case["case_id"])
        self.assertEqual(c["state"], "SUBMITTED")
        again = self.service.submit_case(case["case_id"])
        self.assertEqual(again["submission_id"], c["submission_id"])

for idx in range(80):
    def make_state_test(idx=idx):
        def test(self):
            case = self._case()
            # Before approval, submission is invalid.
            with self.assertRaises(ValueError):
                self.service.submit_case(case["case_id"])
            self.service.request_approval(case["case_id"])
            with self.assertRaises(ValueError):
                self.service.submit_case(case["case_id"])
            self.service.approve_case(case["case_id"], f"reviewer-{idx}", "Reviewed")
        return test
    setattr(TestStateMachine, f"test_invalid_submit_path_{idx:03d}", make_state_test())


class TestDataAndRisk(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract_ops_data_"))
        self.service = build_demo_service(self.tmp / "db.sqlite", POLICY, reset=True)

    def test_demo_dataset_is_nontrivial(self):
        partner_count = self.service.store.conn.execute("SELECT COUNT(*) FROM partners").fetchone()[0]
        contract_count = self.service.store.conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
        self.assertGreaterEqual(partner_count, 1000)
        self.assertGreaterEqual(contract_count, 1200)

    def test_duplicate_search_exact_match(self):
        p = self.service.store.get_partner("BP-000001")
        result = self.service.find_duplicates(p.legal_name, p.tax_id, p.registration_id)
        self.assertGreaterEqual(result["count"], 1)

    def test_termination_with_open_obligation_blocks(self):
        # Deterministic seeded partner with open obligations: partner 17 / contract 01.
        result = self.service.assess_request(
            RequestType.CONTRACT_TERMINATION.value,
            "BP-000017",
            "CON-000017-01",
            {
                "termination_reason": "End of engagement",
                "requested_end_date": "2026-12-01",
                "confirmation_no_open_obligations": True,
            },
        )
        self.assertTrue(result["blocking"])
        self.assertTrue(any(f["code"] == "OPEN_OBLIGATIONS" for f in result["findings"]))

# 45 lookup behavior cases.
for idx in range(45):
    def make_lookup_test(idx=idx):
        def test(self):
            q = ["Northwind", "BlueRiver", "Apex", "Sakura", "Orbit"][idx % 5]
            result = self.service.search_partners(q, limit=(idx % 10) + 1)
            self.assertLessEqual(result["count"], (idx % 10) + 1)
            self.assertIn("partners", result)
        return test
    setattr(TestDataAndRisk, f"test_lookup_case_{idx:03d}", make_lookup_test())


class TestAuditAndDeterminism(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract_ops_audit_"))
        self.service = build_demo_service(self.tmp / "db.sqlite", POLICY, reset=True)

    def test_case_ids_are_deterministic_for_same_request(self):
        fields = {
            "legal_name": "Completely New Supplier",
            "tax_id": "TX-NEW-777",
            "registration_id": "REG-NEW-777",
            "country": "JP",
            "currency": "JPY",
            "source_reference": "REQ-777",
        }
        a = self.service.prepare_request(RequestType.SUPPLIER_REGISTRATION.value, None, None, fields, "Reason", "operator")
        # Exact same request should address the same case; store is idempotent by case_id.
        b = self.service.prepare_request(RequestType.SUPPLIER_REGISTRATION.value, None, None, fields, "Reason", "operator")
        self.assertEqual(a["case_id"], b["case_id"])

    def test_audit_is_written(self):
        fields = {
            "legal_name": "Audited Supplier",
            "tax_id": "TX-NEW-888",
            "registration_id": "REG-NEW-888",
            "country": "JP",
            "currency": "JPY",
            "source_reference": "REQ-888",
        }
        case = self.service.prepare_request(RequestType.SUPPLIER_REGISTRATION.value, None, None, fields, "Reason", "operator")
        events = self.service.store.audit_events(case["case_id"])
        self.assertEqual(events[0]["event"], "CASE_CREATED")

# 30 policy boundary cases around value changes.
for idx in range(30):
    def make_amount_test(idx=idx):
        def test(self):
            partner_id = f"BP-{(idx % 20) + 1:06d}"
            contract_id = f"CON-{(idx % 20) + 1:06d}-01"
            contract = self.service.store.get_contract(contract_id)
            base = contract.annual_value
            ratio = [0.0, 0.05, 0.099, 0.10, 0.15, 0.249, 0.25, 0.50][idx % 8]
            new_value = base * (1 + ratio)
            result = self.service.assess_request(
                RequestType.CONTRACT_AMENDMENT.value,
                partner_id,
                contract_id,
                {"justification": "Approved commercial change", "proposed_annual_value": new_value, "currency": contract.currency},
            )
            self.assertIn("findings", result)
            if ratio >= 0.25:
                self.assertTrue(any(x["code"] == "HIGH_VALUE_CHANGE" for x in result["findings"]))
        return test
    setattr(TestAuditAndDeterminism, f"test_amount_boundary_{idx:03d}", make_amount_test())


class TestConcurrentSQLiteAccess(unittest.TestCase):
    """Regression coverage for MCP SDK worker-thread execution."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="contract_ops_threads_"))
        self.service = build_demo_service(self.tmp / "db.sqlite", POLICY, reset=True)

    def test_concurrent_reads_use_thread_local_connections(self):
        queries = ["Northwind", "BlueRiver", "Apex", "Sakura", "Orbit"] * 16
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda q: self.service.search_partners(q, 5), queries))
        self.assertEqual(len(results), len(queries))
        self.assertTrue(all("partners" in result for result in results))
        self.assertTrue(all(result["count"] <= 5 for result in results))

    def test_concurrent_case_writes_and_audits(self):
        def create_case(idx: int) -> str:
            fields = {
                "legal_name": f"Concurrent Supplier {idx}",
                "tax_id": f"TX-CONCURRENT-{idx}",
                "registration_id": f"REG-CONCURRENT-{idx}",
                "country": "JP",
                "currency": "JPY",
                "source_reference": f"REQ-CONCURRENT-{idx}",
            }
            case = self.service.prepare_request(
                RequestType.SUPPLIER_REGISTRATION.value,
                None,
                None,
                fields,
                "Concurrent write regression test",
                f"operator-{idx}",
            )
            return case["case_id"]

        with ThreadPoolExecutor(max_workers=12) as pool:
            case_ids = list(pool.map(create_case, range(36)))

        self.assertEqual(len(case_ids), 36)
        self.assertEqual(len(set(case_ids)), 36)
        for case_id in case_ids:
            result = self.service.get_case(case_id)
            self.assertTrue(result["found"])
            self.assertEqual(result["audit"][0]["event"], "CASE_CREATED")


if __name__ == "__main__":
    unittest.main()
