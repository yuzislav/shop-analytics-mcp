# MCP Server Evaluation Implementation Plan

Here is a comprehensive evaluation implementation plan designed to be fed into an AI coding agent (like Cursor or Claude Code). Use this plan as a Test-Driven Development (TDD) checklist.

## Phase 1: Environment & Lifecycle Evals
These tests ensure the MCP server starts correctly, binds to `stdio`, and exposes a valid tool schema without hardcoded paths.

| Eval Name | Test Action | Expected Result (Success Criteria) |
| :--- | :--- | :--- |
| **Startup Check** | Run `node path/to/server.js` or `python path/to/server.py` | Process stays alive, listens on `stdio`, and does not crash. |
| **Tool Discovery** | Send `tools/list` JSON-RPC request to the server. | Returns a valid JSON schema with at least one tool (e.g., `query_database` or specialized tools). Descriptions and parameters are fully populated. |
| **Path Resolution** | Move `shop.db` to a different folder and pass the new path via an environment variable (e.g., `DB_PATH`). | Server connects successfully. It does not fail due to hardcoded absolute paths in the source code. |

## Phase 2: Security & Safety Evals (Critical)
These tests verify that the database remains strictly read-only and destructive operations are blocked at the MCP level.

| Eval Name | User Prompt / Agent Action | Expected Result (Success Criteria) |
| :--- | :--- | :--- |
| **Block DELETE** | "Delete all cancelled orders." | The agent refuses or the MCP server intercepts the `DELETE` query, returning a clear error. The database is unmodified. |
| **Block UPDATE** | "Update the price of product ID 5 to 100." | MCP server returns a read-only restriction error. Data remains unchanged. |
| **Block DROP** | "Drop the customers table." | MCP server intercepts the `DROP` keyword and returns an error. Table remains intact. |
| **Schema Protection** | "Create a new table called test_table." | MCP server returns an error blocking `CREATE`. |

## Phase 3: Functional Task Evals
These are the core end-to-end tests. To automate this, you should populate `shop.db` with a known seed dataset so the answers are deterministic.

*   **Task 1: Schema Discovery**
    *   **Prompt:** "Show me all available tables and explain what information each table contains."
    *   **Evaluation:** Agent must successfully query the `sqlite_master` table (or use a dedicated `list_tables` tool) and list `customers`, `products`, `orders`, and `order_items` with accurate descriptions of their columns.
*   **Task 2: Simple Filtering**
    *   **Prompt:** "How many customers are from Germany?"
    *   **Evaluation:** Agent successfully executes a `SELECT COUNT(*) FROM customers WHERE country = 'Germany'` (or equivalent) and returns the correct integer.
*   **Task 3: Aggregation & Grouping**
    *   **Prompt:** "Which country has the most customers?"
    *   **Evaluation:** Agent must return the country name and the specific count. Requires `GROUP BY country ORDER BY count DESC LIMIT 1`.
*   **Task 4: Multi-Table Joins (Customer Spending)**
    *   **Prompt:** "Who is the customer who spent the most money?"
    *   **Evaluation:** Agent returns Name, Email, and Total Amount. Requires joining `customers`, `orders`, `order_items`, and `products` (if price is in products), aggregating the total sum, and sorting. 
*   **Task 5: Top Products by Revenue**
    *   **Prompt:** "What are the top 5 best-selling products?"
    *   **Evaluation:** Agent returns a list of 5 products with Name, Units Sold, and Revenue. Requires joining `products` and `order_items`.
*   **Task 6: Category Aggregation**
    *   **Prompt:** "What are the top 3 product categories by revenue?"
    *   **Evaluation:** Agent identifies categories, aggregates revenue across `orders` -> `order_items` -> `products`, and returns the top 3.
*   **Task 7: Date Filtering**
    *   **Prompt:** "How much revenue did we generate in 2025?"
    *   **Evaluation:** Agent must successfully filter the `orders` table by date (e.g., `WHERE order_date LIKE '2025-%'`), join with items/products, and sum the revenue.
*   **Task 8: Order Frequency**
    *   **Prompt:** "Which customer placed the most orders?"
    *   **Evaluation:** Agent returns the customer name and the exact order count. Requires joining `customers` and `orders`.

## Phase 4: Robustness & Bonus Evals
These evals test the "Bonus" requirements to ensure the MCP is production-ready for an LLM context window.

| Eval Name | User Prompt / Agent Action | Expected Result (Success Criteria) |
| :--- | :--- | :--- |
| **Row Limiting** | "Select all customers." (Assuming DB has >10,000 rows). | MCP automatically truncates/paginates the response (e.g., adding `LIMIT 100`) to prevent context window overflow. |
| **Error Masking** | "Run this query: `SELECT * FROM nonexistent_table`" | MCP returns a clean, human-readable SQL error (e.g., "Table does not exist") without dumping raw Python/Node stack traces into the agent's context. |
| **Tool Descriptions** | N/A (Static Analysis) | Tools have explicit descriptions of schema, return types, and constraints (e.g., "Use this to execute read-only SQLite queries. Max 100 rows returned."). |

---

## How to use this plan with Cursor / Claude Code

To execute this plan iteratively, paste the following prompt into your AI coding agent alongside the requirements:

> **System Prompt for Agent:**
> You are tasked with building the `shop.db` MCP Server described in the requirements. We will use a Test-Driven approach based on the Evaluation Plan provided. 
> 
> **Step 1:** Generate the initial MCP server code (Python/Node) ensuring all Security Evals (Phase 2) are handled by a strict read-only regex/parser or SQLite read-only connection mode.
> **Step 2:** Expose a flexible `query_database` tool OR a set of specific tools. Write rich descriptions for the LLM.
> **Step 3:** Generate a test script that programmatically calls the MCP server with the 8 prompts from Phase 3. 
> **Step 4:** Run the test script. If any prompt fails to yield the exact required data, modify the MCP server tools, constraints, or descriptions until all 8 tasks pass. Do not stop until the Phase 3 Functional Evals are 100% green.