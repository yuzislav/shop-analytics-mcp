You are an expert Python developer. Please implement a read-only Model Context Protocol (MCP) server for a SQLite database (`shop.db`) with rigorous unit tests and a contract smoke test.

**1. Core Architecture & Stack**
*   **Frameworks:** Python 3.10+, `mcp` SDK (use `FastMCP`), `sqlite3`, `pytest`.
*   **Initialization:** The database path should be read from the `SHOP_DB_PATH` environment variable, falling back to `shop.db` in the current working directory. The server must communicate via `stdio`.

**2. MCP Tools to Implement**
*   **`get_database_schema`**: Queries `sqlite_master` or `PRAGMA table_info` and returns the DDL (CREATE TABLE statements) for all tables.
*   **`execute_read_only_sql`**: Accepts a single `query` string, executes it, and returns the result rows as formatted JSON.
    *   *Security Failsafe:* Parse the query using regex and strictly block any query containing mutation keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, `TRUNCATE`). Return a clear security error string if triggered.
    *   *Context Protection:* Automatically append `LIMIT 100` to the query if no limit is explicitly provided.
    *   *Error Handling:* Catch `sqlite3.Error` and return the exception message textually.

**3. Unit Tests (`pytest`)**
*   Create `tests/test_server.py`.
*   Use an in-memory SQLite database (`:memory:`) populated with dummy data for testing.
*   Write tests to assert:
    *   Schema retrieval works correctly.
    *   A valid `SELECT` statement returns data.
    *   A query with `DELETE` or `UPDATE` is successfully blocked by the security failsafe.
    *   Queries without limits are automatically constrained.

**4. Contract Smoke Test (`tests/smoke_test.py`)**
*   Create a lightweight script that does NOT use an LLM.
*   Use the `mcp.client` to connect to your server as a `stdio` subprocess.
*   Programmatically call `get_database_schema` and `execute_read_only_sql` (e.g., `SELECT 1`).
*   Assert that the server successfully receives the tool calls, executes them, and returns valid JSON-RPC responses without crashing.

**5. Execution & Deliverables**
*   Autonomously run `pytest` and `python tests/smoke_test.py` in the terminal to verify the code. Fix any failing tests.
*   Create a `README.md` explaining installation, configuration, execution, and how an external agent can connect via stdio.
*   Output the final project structure and summarize the security measures implemented.