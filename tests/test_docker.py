import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_docker_test():
    # We will launch the docker container passing stdio
    server_params = StdioServerParameters(
        command="docker",
        args=["run", "-i", "--rm", "-e", "SHOP_DB_PATH=/app/shop.db", "shop-analytics-mcp"]
    )

    print("Connecting to Docker MCP server...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1. List tools
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"[OK] Tools available: {tool_names}")
            assert "get_database_schema" in tool_names
            assert "execute_read_only_sql" in tool_names
            assert "get_table_summary" in tool_names

            # 2. Call get_table_summary
            summary_res = await session.call_tool("get_table_summary", {"table_name": "customers"})
            assert summary_res.content
            print(f"[OK] get_table_summary returned: {summary_res.content[0].text[:100]}...")

            # 3. Call execute_read_only_sql with pagination
            sql_res = await session.call_tool("execute_read_only_sql", {"query": "SELECT * FROM customers", "limit": 1})
            assert sql_res.content
            print(f"[OK] execute_read_only_sql returned: {sql_res.content[0].text}")

    print("\n✅ Docker MCP server is working correctly!")

if __name__ == "__main__":
    asyncio.run(run_docker_test())
