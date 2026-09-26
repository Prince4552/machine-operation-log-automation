from __future__ import annotations

"""Real MCP runtime verifier. Run locally after installing mcp>=2,<3.

This is intentionally separate from the large dependency-free suite because the
execution environment used to build this package may not have network access.
It uses the official SDK's documented in-memory Client(server) test path, which
exercises the actual MCP protocol implementation without requiring a port.
"""

import asyncio
import sys
from pathlib import Path

from mcp import Client

from contract_ops_mcp.mcp_server.server import mcp


async def main() -> int:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        expected = {
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
        missing = expected - names
        if missing:
            raise AssertionError(f"Missing MCP tools: {sorted(missing)}")

        result = await client.call_tool("search_business_partners", {"query": "Northwind", "limit": 3})
        if result.is_error or not result.structured_content or result.structured_content.get("count", 0) > 3:
            raise AssertionError("search_business_partners MCP call failed")

        # MCP tool handlers are executed by the SDK in worker threads. Run
        # concurrent calls through the real MCP protocol to catch shared-DB
        # connection/threading regressions.
        concurrent_results = await asyncio.gather(
            *(client.call_tool("search_business_partners", {"query": q, "limit": 5})
              for q in ("Northwind", "BlueRiver", "Apex", "Sakura", "Orbit") * 8)
        )
        if any(r.is_error or not r.structured_content for r in concurrent_results):
            raise AssertionError("Concurrent MCP tool calls failed")

        resource_list = await client.list_resources()
        if not any(str(r.uri) == "contract-ops://policy" for r in resource_list.resources):
            raise AssertionError("Policy resource was not listed")
        policy = await client.read_resource("contract-ops://policy")
        if not policy.contents:
            raise AssertionError("Policy resource returned no content")

        print(f"MCP runtime verification: PASS ({len(names)} tools, policy resource, live in-memory tool call)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
