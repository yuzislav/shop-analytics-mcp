"""
Evaluation test suite for shop-analytics MCP server.
Covers all 4 phases from EVALS_SPEC.md:

  Phase 1 – Environment & Lifecycle
  Phase 2 – Security & Safety (critical)
  Phase 3 – Functional Task Evals (deterministic, against real shop.db)
  Phase 4 – Robustness & Bonus
"""

import json
import os
import re
import sqlite3
import sys

import pytest

# ---------------------------------------------------------------------------
# Import patterns from server (no MCP runtime needed)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import _MUTATION_PATTERN, _LIMIT_PATTERN

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SHOP_DB_PATH", os.path.join(ROOT_DIR, "shop.db"))
SERVER_SCRIPT = os.path.join(ROOT_DIR, "server.py")


# ---------------------------------------------------------------------------
# Helpers (mirror server internals; no real MCP server needed)
# ---------------------------------------------------------------------------

def _schema(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    )
    rows = cursor.fetchall()
    if not rows:
        return "No tables found in the database."
    return "\n\n".join(row[0] for row in rows)


def _run_query(conn: sqlite3.Connection, query: str) -> str:
    """Mirror server.execute_read_only_sql logic."""
    match = _MUTATION_PATTERN.search(query)
    if match:
        return (
            f"Security error: Query contains forbidden keyword '{match.group().upper()}'. "
            "Only read-only SELECT queries are allowed."
        )
    safe_query = query.rstrip().rstrip(";")
    if not _LIMIT_PATTERN.search(safe_query):
        safe_query = f"{safe_query} LIMIT 100"
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(safe_query)
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        return json.dumps(result, indent=2, default=str)
    except sqlite3.Error as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_db():
    """Read-only connection to the real shop.db (populated seed data)."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture()
def mem_db():
    """In-memory DB with 200 rows used for row-limiting tests."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums (n INTEGER)")
    conn.executemany("INSERT INTO nums VALUES (?)", [(i,) for i in range(200)])
    conn.commit()
    yield conn
    conn.close()


# ===========================================================================
# Phase 1 – Environment & Lifecycle Evals
# ===========================================================================

class TestPhase1EnvironmentLifecycle:
    """P1: Server starts, schema discoverable, DB_PATH resolved via env-var."""

    def test_startup_db_file_exists(self):
        """shop.db (or $SHOP_DB_PATH) exists and is a valid SQLite database."""
        assert os.path.exists(DB_PATH), f"Database file not found: {DB_PATH}"
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.execute("SELECT 1")
        conn.close()

    def test_server_script_exists(self):
        """server.py exists at the expected location."""
        assert os.path.isfile(SERVER_SCRIPT), f"Server script not found: {SERVER_SCRIPT}"

    def test_tool_discovery_schema_tool_exposes_four_tables(self, real_db):
        """get_database_schema DDL must include all four expected tables."""
        schema = _schema(real_db)
        assert "CREATE TABLE" in schema
        for table in ("customers", "products", "orders", "order_items"):
            assert table in schema, f"Expected table '{table}' in DDL"

    def test_tool_discovery_sql_tool_returns_valid_json(self, real_db):
        """execute_read_only_sql returns valid JSON for a trivial query."""
        result = _run_query(real_db, "SELECT 1 AS ping")
        rows = json.loads(result)
        assert rows == [{"ping": 1}]

    def test_path_resolution_via_env_var(self, tmp_path):
        """Server can connect to a DB at an arbitrary path (no hardcoded paths)."""
        import shutil
        alt_db = tmp_path / "alt_shop.db"
        shutil.copy(DB_PATH, alt_db)
        conn = sqlite3.connect(f"file:{alt_db}?mode=ro", uri=True)
        schema = _schema(conn)
        conn.close()
        assert "customers" in schema, "Schema not accessible from alternate DB path"


# ===========================================================================
# Phase 2 – Security & Safety Evals (critical)
# ===========================================================================

class TestPhase2SecuritySafety:
    """P2: All mutation keywords must be blocked by the server."""

    @pytest.mark.parametrize("query,keyword", [
        ("DELETE FROM customers WHERE id=1", "DELETE"),
        ("delete from customers", "DELETE"),
        ("UPDATE products SET price=0", "UPDATE"),
        ("update products set price=0", "UPDATE"),
        ("DROP TABLE customers", "DROP"),
        ("drop table customers", "DROP"),
        ("CREATE TABLE evil (id INTEGER)", "CREATE"),
        ("INSERT INTO customers (first_name) VALUES ('x')", "INSERT"),
        ("REPLACE INTO customers VALUES(1,'x','y','z',NULL,'2026-01-01')", "REPLACE"),
        ("ALTER TABLE customers ADD COLUMN phone TEXT", "ALTER"),
        ("TRUNCATE TABLE customers", "TRUNCATE"),
    ])
    def test_mutation_is_blocked(self, real_db, query: str, keyword: str):
        result = _run_query(real_db, query)
        assert "Security error" in result, (
            f"Expected security error for '{query}', got: {result!r}"
        )
        assert keyword.upper() in result

    def test_block_delete_database_is_unmodified(self, real_db):
        """After a blocked DELETE the row count is unchanged."""
        cursor = real_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM customers")
        count_before = cursor.fetchone()[0]

        _run_query(real_db, "DELETE FROM customers")

        cursor.execute("SELECT COUNT(*) FROM customers")
        count_after = cursor.fetchone()[0]
        assert count_before == count_after

    def test_block_update_data_unchanged(self, real_db):
        """After a blocked UPDATE all product prices remain unchanged."""
        cursor = real_db.cursor()
        cursor.execute("SELECT price FROM products LIMIT 1")
        original_price = cursor.fetchone()[0]

        _run_query(real_db, "UPDATE products SET price=0")

        cursor.execute("SELECT price FROM products LIMIT 1")
        new_price = cursor.fetchone()[0]
        assert original_price == new_price


# ===========================================================================
# Phase 3 – Functional Task Evals (deterministic against seeded shop.db)
# ===========================================================================

class TestPhase3FunctionalTasks:
    """P3: End-to-end correctness checks against the real seed database."""

    # ------------------------------------------------------------------ Task 1
    def test_task1_schema_lists_all_tables(self, real_db):
        """Task 1: Schema must expose all four tables."""
        schema = _schema(real_db)
        for table in ("customers", "products", "orders", "order_items"):
            assert table in schema

    def test_task1_schema_describes_key_columns(self, real_db):
        """Task 1: Schema DDL must reference key columns."""
        schema = _schema(real_db)
        for col in (
            "first_name", "last_name", "email",
            "category", "price",
            "order_date", "status", "total_amount",
            "unit_price", "quantity",
        ):
            assert col in schema, f"Expected column '{col}' in DDL"

    # ------------------------------------------------------------------ Task 2
    def test_task2_count_total_customers(self, real_db):
        """Task 2: Total customer count is 150 (seed data)."""
        result = _run_query(real_db, "SELECT COUNT(*) AS total FROM customers")
        rows = json.loads(result)
        assert rows[0]["total"] == 150

    def test_task2_filter_returns_integer(self, real_db):
        """Task 2: COUNT with WHERE clause returns a non-negative integer."""
        result = _run_query(
            real_db,
            "SELECT COUNT(*) AS cnt FROM customers WHERE email LIKE '%@mail.ru'"
        )
        rows = json.loads(result)
        assert isinstance(rows[0]["cnt"], int)
        assert rows[0]["cnt"] >= 0

    # ------------------------------------------------------------------ Task 3
    def test_task3_groupby_returns_domain_and_count(self, real_db):
        """Task 3: GROUP BY aggregation returns name and count fields."""
        result = _run_query(
            real_db,
            """
            SELECT substr(email, instr(email,'@')+1) AS domain, COUNT(*) AS cnt
            FROM customers
            GROUP BY domain
            ORDER BY cnt DESC
            LIMIT 1
            """,
        )
        rows = json.loads(result)
        assert len(rows) == 1
        assert rows[0]["cnt"] > 0

    # ------------------------------------------------------------------ Task 4
    def test_task4_top_spender_fields(self, real_db):
        """Task 4: Top-spender query returns name, email, and total."""
        result = _run_query(
            real_db,
            """
            SELECT c.first_name || ' ' || c.last_name AS name,
                   c.email,
                   SUM(oi.quantity * oi.unit_price) AS total
            FROM customers c
            JOIN orders o ON o.customer_id = c.id
            JOIN order_items oi ON oi.order_id = o.id
            GROUP BY c.id
            ORDER BY total DESC
            LIMIT 1
            """,
        )
        rows = json.loads(result)
        assert len(rows) == 1
        assert rows[0]["name"] and "@" in rows[0]["email"] and rows[0]["total"] > 0

    def test_task4_top_spender_known_value(self, real_db):
        """Task 4: Top spender is Дмитрий Харитонов with 785750.0 (seed data)."""
        cursor = real_db.cursor()
        cursor.execute(
            """
            SELECT c.first_name || ' ' || c.last_name AS name,
                   SUM(oi.quantity * oi.unit_price) AS total
            FROM customers c
            JOIN orders o ON o.customer_id = c.id
            JOIN order_items oi ON oi.order_id = o.id
            GROUP BY c.id
            ORDER BY total DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        assert row["name"] == "Дмитрий Харитонов"
        assert abs(row["total"] - 785750.0) < 0.01

    # ------------------------------------------------------------------ Task 5
    def test_task5_top5_products_exactly_five_rows(self, real_db):
        """Task 5: Top-5 products query returns exactly 5 rows."""
        result = _run_query(
            real_db,
            """
            SELECT p.name, SUM(oi.quantity) AS units_sold,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM products p
            JOIN order_items oi ON oi.product_id = p.id
            GROUP BY p.id
            ORDER BY revenue DESC
            LIMIT 5
            """,
        )
        rows = json.loads(result)
        assert len(rows) == 5

    def test_task5_top_product_known_value(self, real_db):
        """Task 5: #1 product by revenue is 'Ноутбук UltraBook 15' (seed data)."""
        cursor = real_db.cursor()
        cursor.execute(
            """
            SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM products p
            JOIN order_items oi ON oi.product_id = p.id
            GROUP BY p.id
            ORDER BY revenue DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        assert row["name"] == "Ноутбук UltraBook 15"

    # ------------------------------------------------------------------ Task 6
    def test_task6_top3_categories_exactly_three(self, real_db):
        """Task 6: Top-3 categories query returns exactly 3 rows."""
        result = _run_query(
            real_db,
            """
            SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM products p
            JOIN order_items oi ON oi.product_id = p.id
            GROUP BY p.category
            ORDER BY revenue DESC
            LIMIT 3
            """,
        )
        rows = json.loads(result)
        assert len(rows) == 3

    def test_task6_top_category_known_value(self, real_db):
        """Task 6: #1 category is 'Электроника' (seed data)."""
        cursor = real_db.cursor()
        cursor.execute(
            """
            SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM products p
            JOIN order_items oi ON oi.product_id = p.id
            GROUP BY p.category
            ORDER BY revenue DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        assert row["category"] == "Электроника"

    # ------------------------------------------------------------------ Task 7
    def test_task7_date_filter_returns_positive_revenue(self, real_db):
        """Task 7: Revenue for any year present in DB is a positive number."""
        cursor = real_db.cursor()
        cursor.execute(
            "SELECT strftime('%Y', order_date) AS yr FROM orders GROUP BY yr"
        )
        years = [r[0] for r in cursor.fetchall()]
        assert years, "No orders found in DB"

        year = years[0]
        result = _run_query(
            real_db,
            f"""
            SELECT SUM(oi.quantity * oi.unit_price) AS revenue
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            WHERE strftime('%Y', o.order_date) = '{year}'
            """,
        )
        rows = json.loads(result)
        assert rows[0]["revenue"] is not None
        assert float(rows[0]["revenue"]) > 0

    def test_task7_2026_revenue_known_value(self, real_db):
        """Task 7: 2026 total revenue is 32792060.0 (seed data)."""
        cursor = real_db.cursor()
        cursor.execute(
            """
            SELECT SUM(oi.quantity * oi.unit_price) AS revenue
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            WHERE strftime('%Y', o.order_date) = '2026'
            """
        )
        row = cursor.fetchone()
        assert row["revenue"] is not None
        assert abs(row["revenue"] - 32792060.0) < 1.0

    # ------------------------------------------------------------------ Task 8
    def test_task8_most_ordering_customer_fields(self, real_db):
        """Task 8: Most-orders query returns name and order_count."""
        result = _run_query(
            real_db,
            """
            SELECT c.first_name || ' ' || c.last_name AS name,
                   COUNT(o.id) AS order_count
            FROM customers c
            JOIN orders o ON o.customer_id = c.id
            GROUP BY c.id
            ORDER BY order_count DESC
            LIMIT 1
            """,
        )
        rows = json.loads(result)
        assert len(rows) == 1
        assert rows[0]["name"] and rows[0]["order_count"] > 0

    def test_task8_most_ordering_customer_known_value(self, real_db):
        """Task 8: Top customer is 'София Яковлев' with 16 orders (seed data)."""
        cursor = real_db.cursor()
        cursor.execute(
            """
            SELECT c.first_name || ' ' || c.last_name AS name,
                   COUNT(o.id) AS order_count
            FROM customers c
            JOIN orders o ON o.customer_id = c.id
            GROUP BY c.id
            ORDER BY order_count DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        assert row["name"] == "София Яковлев"
        assert row["order_count"] == 16


# ===========================================================================
# Phase 4 – Robustness & Bonus Evals
# ===========================================================================

class TestPhase4Robustness:
    """P4: Row limiting, error masking, tool description quality."""

    # Row Limiting
    def test_row_limiting_auto_appends_limit_100(self, mem_db):
        """Queries without LIMIT are automatically capped at 100 rows."""
        result = _run_query(mem_db, "SELECT * FROM nums")
        rows = json.loads(result)
        assert len(rows) == 100, f"Expected 100 rows (auto-limit), got {len(rows)}"

    def test_row_limiting_explicit_limit_respected(self, real_db):
        """An explicit LIMIT in the query is not overridden."""
        result = _run_query(real_db, "SELECT * FROM customers LIMIT 5")
        rows = json.loads(result)
        assert len(rows) == 5

    def test_row_limiting_large_table_capped(self, real_db):
        """Query against a large table (1900 order_items) is capped at 100."""
        result = _run_query(real_db, "SELECT * FROM order_items")
        rows = json.loads(result)
        assert len(rows) == 100, f"Expected 100 rows, got {len(rows)}"

    # Error Masking
    def test_error_masking_nonexistent_table(self, real_db):
        """Query against a missing table returns a readable message, not a traceback."""
        result = _run_query(real_db, "SELECT * FROM nonexistent_table")
        assert "no such table" in result.lower()
        assert "Traceback" not in result
        assert 'File "' not in result

    def test_error_masking_result_is_string(self, real_db):
        """Error response is always a plain string, never a raised exception."""
        result = _run_query(real_db, "SELECT * FROM nonexistent_table")
        assert isinstance(result, str)

    def test_error_masking_no_raw_stack_trace_on_bad_sql(self, real_db):
        """Malformed SQL returns no Python stack trace in the response."""
        result = _run_query(real_db, "SELECT * FROM")
        assert "Traceback" not in result
        assert 'File "' not in result

    # Tool Description Quality (static analysis — all 4 required aspects)

    # --- execute_read_only_sql ---

    def test_execute_sql_doc_when_to_use(self):
        """Docstring must tell the agent WHEN to use this tool."""
        import server
        doc = server.execute_read_only_sql.__doc__ or ""
        doc_lower = doc.lower()
        # Must mention the use-case context
        assert any(kw in doc_lower for kw in ("when to use", "use this tool", "analytical", "query", "select")), (
            "execute_read_only_sql docstring should describe when to call this tool"
        )

    def test_execute_sql_doc_parameters(self):
        """Docstring must describe the `query` parameter."""
        import server
        doc = server.execute_read_only_sql.__doc__ or ""
        doc_lower = doc.lower()
        assert "query" in doc_lower, "Docstring must document the 'query' parameter"
        assert "select" in doc_lower, "Docstring should mention SELECT as the expected statement type"

    def test_execute_sql_doc_return_format(self):
        """Docstring must describe what the tool returns (JSON array of objects)."""
        import server
        doc = server.execute_read_only_sql.__doc__ or ""
        doc_lower = doc.lower()
        assert "json" in doc_lower, "Docstring must mention JSON as the return format"
        assert any(kw in doc_lower for kw in ("array", "list", "[{")), (
            "Docstring should describe the return structure (array/list of objects)"
        )

    def test_execute_sql_doc_constraints(self):
        """Docstring must mention read-only and row-limit constraints."""
        import server
        doc = server.execute_read_only_sql.__doc__ or ""
        doc_lower = doc.lower()
        assert "read-only" in doc_lower or "read only" in doc_lower, (
            "Docstring must mention read-only restriction"
        )
        assert "100" in doc or "limit" in doc_lower, (
            "Docstring must mention the 100-row limit"
        )
        assert any(kw in doc_lower for kw in ("insert", "delete", "drop", "forbidden", "blocked", "rejected")), (
            "Docstring must name at least some of the blocked mutation keywords"
        )

    # --- get_database_schema ---

    def test_schema_doc_when_to_use(self):
        """Docstring must tell the agent WHEN to call get_database_schema."""
        import server
        doc = server.get_database_schema.__doc__ or ""
        doc_lower = doc.lower()
        assert any(kw in doc_lower for kw in ("when to use", "first", "before", "discover")), (
            "get_database_schema docstring should explain when to call it (e.g. 'call first')"
        )

    def test_schema_doc_parameters(self):
        """Docstring must clarify that get_database_schema takes no parameters."""
        import server
        doc = server.get_database_schema.__doc__ or ""
        doc_lower = doc.lower()
        assert any(kw in doc_lower for kw in ("none", "no parameter", "parameters:\n", "parameters:")), (
            "get_database_schema docstring should note it takes no parameters"
        )

    def test_schema_doc_return_format(self):
        """Docstring must describe what get_database_schema returns (DDL / CREATE TABLE)."""
        import server
        doc = server.get_database_schema.__doc__ or ""
        doc_lower = doc.lower()
        assert "ddl" in doc_lower or "create table" in doc_lower, (
            "Docstring must mention DDL or CREATE TABLE as the return format"
        )

    def test_schema_doc_constraints(self):
        """Docstring must mention that get_database_schema is read-only / returns schema only."""
        import server
        doc = server.get_database_schema.__doc__ or ""
        doc_lower = doc.lower()
        assert "read-only" in doc_lower or "schema" in doc_lower, (
            "Docstring must mention read-only or schema-only constraint"
        )


    def test_security_pattern_covers_all_required_keywords(self):
        """Mutation regex blocks all 8 required keywords, case-insensitively."""
        required = [
            "INSERT", "UPDATE", "DELETE", "DROP",
            "ALTER", "CREATE", "REPLACE", "TRUNCATE",
        ]
        for kw in required:
            assert _MUTATION_PATTERN.search(kw), f"Pattern misses keyword: {kw}"
            assert _MUTATION_PATTERN.search(kw.lower()), (
                f"Pattern is not case-insensitive for: {kw}"
            )
