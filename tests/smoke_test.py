"""
Contract smoke test for shop-analytics MCP server.

Launches the server as a stdio subprocess via the MCP client SDK,
calls both tools, and asserts valid responses are received — no LLM involved.
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shop.db")


async def run_smoke_test():
    env = {**os.environ, "SHOP_DB_PATH": DB_PATH}

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
        env=env,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # ----------------------------------------------------------------
            # 1. List available tools
            # ----------------------------------------------------------------
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            assert "get_database_schema" in tool_names, (
                f"Expected 'get_database_schema' in tools, got: {tool_names}"
            )
            assert "execute_read_only_sql" in tool_names, (
                f"Expected 'execute_read_only_sql' in tools, got: {tool_names}"
            )
            print(f"[OK] Tools registered: {tool_names}")

            # ----------------------------------------------------------------
            # 2. Call get_database_schema
            # ----------------------------------------------------------------
            schema_result = await session.call_tool("get_database_schema", {})
            assert schema_result.content, "get_database_schema returned empty content"
            schema_text = schema_result.content[0].text
            assert "CREATE TABLE" in schema_text, (
                f"Expected DDL in schema output, got: {schema_text!r}"
            )
            print(f"[OK] get_database_schema returned DDL ({len(schema_text)} chars)")

            # ----------------------------------------------------------------
            # 3. Call execute_read_only_sql with a benign query
            # ----------------------------------------------------------------
            sql_result = await session.call_tool(
                "execute_read_only_sql", {"query": "SELECT 1 AS ping"}
            )
            assert sql_result.content, "execute_read_only_sql returned empty content"
            sql_text = sql_result.content[0].text
            rows = json.loads(sql_text)
            assert rows == [{"ping": 1}], f"Unexpected rows: {rows}"
            print(f"[OK] execute_read_only_sql('SELECT 1 AS ping') -> {rows}")

            # ----------------------------------------------------------------
            # 4. Verify security failsafe via the MCP transport
            # ----------------------------------------------------------------
            blocked_result = await session.call_tool(
                "execute_read_only_sql", {"query": "DELETE FROM customers"}
            )
            blocked_text = blocked_result.content[0].text
            assert "Security error" in blocked_text, (
                f"Expected security error, got: {blocked_text!r}"
            )
            print(f"[OK] Security failsafe triggered correctly")

    print("\n✅  All smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
