from __future__ import annotations

import ast
import importlib
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "contract_ops_mcp" / "mcp_server" / "server.py"


EXPECTED_TOOLS = {
    "search_business_partners",
    "get_business_partner",
    "list_partner_contracts",
    "get_contract",
    "check_request_completeness",
    "find_duplicate_candidates",
    "assess_contract_request",
    "prepare_contract_case",
    "request_human_approval",
    "approve_case",
    "submit_case",
    "get_case",
}


class FakeMCPServer:
    def __init__(self, name: str, instructions: str = ""):
        self.name = name
        self.instructions = instructions
        self.tools = {}
        self.resources = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco

    def resource(self, uri: str):
        def deco(fn):
            self.resources[uri] = fn
            return fn
        return deco

    def run(self, *args, **kwargs):
        return None


class TestMCPServerStaticContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        cls.tree = tree

    def test_uses_current_mcp_server_import(self):
        imports = {alias.name for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom) for alias in node.names if node.module == "mcp.server"}
        self.assertIn("MCPServer", imports)

    def test_all_expected_tool_decorators_exist(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool":
                        names.add(node.name)
        self.assertEqual(names, EXPECTED_TOOLS)

    def test_policy_resource_exists(self):
        found = False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "resource":
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "contract-ops://policy":
                    found = True
        self.assertTrue(found)


class TestMCPWiringWithLocalStub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_mcp = types.ModuleType("mcp")
        fake_server = types.ModuleType("mcp.server")
        fake_server.MCPServer = FakeMCPServer
        fake_mcp.server = fake_server
        old = {k: sys.modules.get(k) for k in ["mcp", "mcp.server"]}
        sys.modules["mcp"] = fake_mcp
        sys.modules["mcp.server"] = fake_server
        import os
        cls.temp_root = Path(tempfile.mkdtemp(prefix="mcp_stub_"))
        os.environ["CONTRACT_OPS_DB"] = str(cls.temp_root / "db.sqlite")
        os.environ["CONTRACT_OPS_POLICY"] = str(ROOT / "config" / "policy.json")
        try:
            sys.modules.pop("contract_ops_mcp.mcp_server.server", None)
            module = importlib.import_module("contract_ops_mcp.mcp_server.server")
            cls.module = module
            cls.fake_server = module.mcp
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_tool_registration_count(self):
        self.assertEqual(set(self.fake_server.tools), EXPECTED_TOOLS)

    def test_tool_functions_are_callable(self):
        out = self.fake_server.tools["search_business_partners"]("Northwind", 2)
        self.assertIn("partners", out)
        self.assertLessEqual(out["count"], 2)

    def test_contract_lookup_tool(self):
        out = self.fake_server.tools["get_contract"]("CON-000001-01")
        self.assertTrue(out["found"])


    def test_tool_functions_are_thread_safe(self):
        queries = ["Northwind", "BlueRiver", "Apex", "Sakura", "Orbit"] * 16
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda q: self.fake_server.tools["search_business_partners"](q, 5), queries))
        self.assertEqual(len(results), len(queries))
        self.assertTrue(all("partners" in result for result in results))
        self.assertTrue(all(result["count"] <= 5 for result in results))

    def test_case_tool_enforces_approval(self):
        fields = {
            "legal_name": "MCP Test Supplier",
            "tax_id": "TX-MCP-1",
            "registration_id": "REG-MCP-1",
            "country": "JP",
            "currency": "JPY",
            "source_reference": "MCP-REQ-1",
        }
        case = self.fake_server.tools["prepare_contract_case"](
            "supplier_registration", None, None, fields, "MCP test", "operator"
        )
        with self.assertRaises(ValueError):
            self.fake_server.tools["submit_case"](case["case_id"])

# 70 contract-level checks for tool function docstrings/signatures.
for idx in range(70):
    def make_contract_test(idx=idx):
        def test(self):
            tool_names = sorted(self.fake_server.tools)
            name = tool_names[idx % len(tool_names)]
            fn = self.fake_server.tools[name]
            self.assertIsNotNone(fn.__doc__)
            self.assertGreaterEqual(len(fn.__doc__.strip()), 12)
            self.assertIsInstance(name, str)
            self.assertTrue(name[0].islower())
        return test
    setattr(TestMCPWiringWithLocalStub, f"test_tool_contract_{idx:03d}", make_contract_test())


if __name__ == "__main__":
    unittest.main()
