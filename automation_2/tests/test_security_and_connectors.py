from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contract_ops_mcp.demo import build_demo_service
from contract_ops_mcp.adapters.rest import RestClient, RestConfig

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "policy.json"


class TestInputSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="security_suite_"))
        cls.service = build_demo_service(cls.tmp / "db.sqlite", POLICY, reset=True)

    def test_limit_boundaries(self):
        self.assertRaises(ValueError, self.service.search_partners, "Apex", 0)
        self.assertRaises(ValueError, self.service.search_partners, "Apex", 51)
        self.assertLessEqual(self.service.search_partners("Apex", 50)["count"], 50)

    def test_blank_queries_rejected(self):
        for value in ["", "   ", "\t", "\n"]:
            with self.subTest(value=repr(value)):
                self.assertRaises(ValueError, self.service.search_partners, value, 10)

    def test_unknown_records_are_safe(self):
        self.assertFalse(self.service.get_partner("DOES-NOT-EXIST")["found"])
        self.assertFalse(self.service.get_contract("DOES-NOT-EXIST")["found"])
        self.assertFalse(self.service.get_case("DOES-NOT-EXIST")["found"])

for idx in range(30):
    malicious = [
        "' OR 1=1 --",
        '" OR "1"="1',
        "; DROP TABLE partners; --",
        "Robert'); DROP TABLE partners;--",
        "../../etc/passwd",
        "${jndi:ldap://evil}",
        "<script>alert(1)</script>",
        "\\x00",
        "Apex%27%20OR%201%3D1",
        "SELECT * FROM partners",
    ][idx % 10]
    def make_injection_test(value=malicious, idx=idx):
        def test(self):
            result = self.service.search_partners(value, 5)
            self.assertIn("partners", result)
            self.assertLessEqual(result["count"], 5)
            # The schema must remain intact after the query.
            check = self.service.search_partners("Apex", 1)
            self.assertLessEqual(check["count"], 1, f"case {idx}")
        return test
    setattr(TestInputSecurity, f"test_query_injection_case_{idx:03d}", make_injection_test())


class TestRestConfig(unittest.TestCase):
    def test_http_and_https_only(self):
        RestClient(RestConfig("https://example.com"))
        RestClient(RestConfig("http://localhost:8000"))
        with self.assertRaises(ValueError):
            RestClient(RestConfig("ftp://example.com"))
        with self.assertRaises(ValueError):
            RestClient(RestConfig("example.com"))

for idx in range(20):
    def make_rest_test(idx=idx):
        def test(self):
            cfg = RestConfig(
                base_url=f"https://system-{idx}.example.internal/api",
                token_env="TOKEN",
                timeout_s=5 + idx / 10,
                max_retries=idx % 4,
            )
            client = RestClient(cfg)
            self.assertTrue(client.config.base_url.startswith("https://"))
            self.assertGreaterEqual(client.config.timeout_s, 5)
            self.assertLessEqual(client.config.max_retries, 3)
        return test
    setattr(TestRestConfig, f"test_rest_config_case_{idx:03d}", make_rest_test())


if __name__ == "__main__":
    unittest.main()
