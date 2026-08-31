"""
Shop Analytics MCP Server
A read-only MCP server exposing a SQLite database via two tools.
"""

import json
import os
import re
import sqlite3

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# Database path resolution
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("SHOP_DB_PATH", "shop.db")

mcp = MCPServer("shop-analytics")

# ---------------------------------------------------------------------------
# Mutation keyword blocklist (compile once at module load)
# ---------------------------------------------------------------------------
_MUTATION_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE)\b",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)


def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return a read-only SQLite connection."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Tool: get_database_schema
# ---------------------------------------------------------------------------
@mcp.tool()
def get_database_schema() -> str:
    """
    Return the full DDL (CREATE TABLE statements) for every table in the database.

    When to use:
        Call this tool FIRST — before writing any SQL query — to discover the
        available tables, their column names, data types, and relationships
        (foreign keys). You must know the schema before querying.

    Parameters:
        None.

    Returns:
        A plain-text string containing one CREATE TABLE statement per table,
        separated by blank lines. Example:

            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                ...
            )

        If the database is empty, returns: "No tables found in the database."
        On connection error, returns a string starting with "Database error:".

    Constraints:
        - Read-only: does not modify the database in any way.
        - Returns schema only, not row data.
    """
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "No tables found in the database."

        ddl_statements = "\n\n".join(row[0] for row in rows)
        return ddl_statements
    except sqlite3.Error as exc:
        return f"Database error: {exc}"


# ---------------------------------------------------------------------------
# Tool: execute_read_only_sql
# ---------------------------------------------------------------------------
@mcp.tool()
def execute_read_only_sql(query: str) -> str:
    """
    Execute a read-only SELECT query against the shop database and return
    the results as a JSON array of objects.

    When to use:
        Use this tool to answer any analytical question about the shop data:
        filtering, aggregation, grouping, joining tables, counting, summing, etc.
        Always call get_database_schema first if you are unsure of table or
        column names.

    Parameters:
        query (str): A valid SQLite SELECT statement. Must not contain
            mutation keywords (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
            REPLACE, TRUNCATE). Trailing semicolons are stripped automatically.

    Returns:
        On success — a JSON string containing an array of row objects, e.g.:
            [{"first_name": "Alice", "total": 1234.56}, ...]
        Row count is capped at 100. If you need fewer rows, add LIMIT explicitly.
        On security violation — a string starting with "Security error:".
        On SQL error — a plain-text SQLite error message (no stack trace).

    Constraints:
        - Read-only: any query containing INSERT / UPDATE / DELETE / DROP /
          ALTER / CREATE / REPLACE / TRUNCATE is rejected immediately.
        - Maximum 100 rows returned per call. Add LIMIT N to override.
        - The underlying SQLite connection is opened in read-only mode (URI
          mode=ro), so writes are impossible even if the keyword filter
          were bypassed.
    """
    # Security failsafe – block mutation keywords
    match = _MUTATION_PATTERN.search(query)
    if match:
        return (
            f"Security error: Query contains forbidden keyword '{match.group().upper()}'. "
            "Only read-only SELECT queries are allowed."
        )

    # Auto-append LIMIT 100 when the query has no explicit limit
    safe_query = query.rstrip().rstrip(";")
    if not _LIMIT_PATTERN.search(safe_query):
        safe_query = f"{safe_query} LIMIT 100"

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(safe_query)
        rows = cursor.fetchall()
        conn.close()

        result = [dict(row) for row in rows]
        return json.dumps(result, indent=2, default=str)
    except sqlite3.Error as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
