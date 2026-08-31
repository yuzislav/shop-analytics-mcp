# Shop Analytics MCP Server

A **read-only** [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes a SQLite database (`shop.db`) to AI agents via two tools.

---

## Features

| Tool | Description |
|------|-------------|
| `get_database_schema` | Returns DDL (CREATE TABLE statements) for all tables |
| `get_table_summary` | Returns a summary of a specific table, including row count and the first 5 sample rows |
| `execute_read_only_sql` | Executes a SELECT query and returns results as JSON. Supports pagination via `limit` and `offset` arguments. |

### Security & Robustness

- **Mutation keyword blocking** – queries containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, or `TRUNCATE` are rejected before reaching the database.
- **Automatic Pagination** – `execute_read_only_sql` automatically caps results at 100 rows, but can be customized with explicit `limit` and `offset` parameters.
- **Read-only SQLite URI** – the database is opened with `?mode=ro`, preventing any writes at the OS level.
- **Structured Errors** – SQL errors are returned as a JSON structure to help agents easily understand and recover from mistakes.

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

---

## 1. Installation

```bash
# Clone / enter the project directory
cd shop-analytics-mcp

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `SHOP_DB_PATH` | `shop.db` | Absolute or relative path to the SQLite database |

---

## 3. Running the Server

The server communicates via **stdio** (standard input/output), which is the transport used by MCP hosts.

### Running Locally

```bash
# Run with the default shop.db in the current directory
python server.py

# Run with a custom database path
SHOP_DB_PATH=/path/to/my.db python server.py
```

### Running with Docker

You can run the server in an isolated Docker container. Since MCP uses stdio, you must run the container in interactive mode (`-i`).

```bash
docker build -t shop-analytics-mcp .

# Run the container (reads and writes to stdio)
docker run -i --rm shop-analytics-mcp
```

---

## 4. Connecting to Agent

Any MCP-compatible host can connect to this server via stdio.

### Agent Configuration (`mcp.json`)

```json
{
  "mcpServers": {
    "shop-analytics": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/shop-analytics-mcp/server.py"],
      "env": {
        "SHOP_DB_PATH": "/path/to/shop.db"
      }
    }
  }
}
```

### Programmatic (Python MCP client SDK)

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="python",
        args=["server.py"],
        env={"SHOP_DB_PATH": "shop.db"},
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_database_schema", {})
            print(result.content[0].text)

asyncio.run(main())
```

---

## Running Tests

### Unit Tests

```bash
pytest tests/test_server.py -v
```

### Evaluation Test Suite

Comprehensive evaluation suite covering all phases defined in `EVALS_SPEC.md` (Environment, Security, Functional Tasks, and Robustness).

```bash
pytest tests/test_evals.py -v
```

### Contract Smoke Test

The smoke test launches the server as a subprocess and exercises both tools via the MCP client SDK — no LLM required.

```bash
python tests/smoke_test.py
```

---

## Project Structure

```
shop-analytics-mcp/
├── server.py           # FastMCP server (entry point)
├── create_shop_db.py   # One-time script to create demo shop.db
├── Dockerfile          # Docker image configuration
├── .dockerignore       # Files to ignore in Docker context
├── requirements.txt
├── README.md
├── SPEC.md             # Initial project specification
├── EVALS_SPEC.md       # Evaluation implementation plan
└── tests/
    ├── test_server.py  # pytest unit tests (in-memory SQLite)
    ├── test_evals.py   # Comprehensive TDD evaluation suite
    └── smoke_test.py   # Contract smoke test (stdio subprocess)
```
