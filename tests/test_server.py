"""
Unit tests for shop-analytics MCP server tools.
Uses an in-memory SQLite database – no real shop.db required.
"""

import json
import sqlite3
import sys
import os
import re
import pytest

# ---------------------------------------------------------------------------
# Import the logic under test without starting the MCP server
# ---------------------------------------------------------------------------
# We replicate the core logic here so tests are fast and side-effect-free.
# The actual server module is imported for its regex patterns.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import _MUTATION_PATTERN, _LIMIT_PATTERN


# ---------------------------------------------------------------------------
# Helpers that mirror server logic but accept an explicit connection
# ---------------------------------------------------------------------------

def schema_for(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    )
    rows = cursor.fetchall()
    if not rows:
        return "No tables found in the database."
    return "\n\n".join(row[0] for row in rows)


def execute_query(conn: sqlite3.Connection, query: str) -> str:
    # Security failsafe
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

@pytest.fixture()
def db():
    """In-memory SQLite database pre-populated with test data."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE customers (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL
        );
        CREATE TABLE products (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            price REAL NOT NULL
        );
        INSERT INTO customers (name, email) VALUES
            ('Alice', 'alice@test.com'),
            ('Bob',   'bob@test.com');
        INSERT INTO products (name, price) VALUES
            ('Widget', 9.99),
            ('Gadget', 19.99),
            ('Doohickey', 4.99);
    """)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetDatabaseSchema:
    def test_returns_ddl_for_all_tables(self, db):
        result = schema_for(db)
        assert "CREATE TABLE customers" in result
        assert "CREATE TABLE products" in result

    def test_empty_database_returns_message(self):
        empty_conn = sqlite3.connect(":memory:")
        result = schema_for(empty_conn)
        assert result == "No tables found in the database."
        empty_conn.close()


class TestExecuteReadOnlySql:
    def test_valid_select_returns_data(self, db):
        result = execute_query(db, "SELECT * FROM customers")
        rows = json.loads(result)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[1]["name"] == "Bob"

    def test_select_with_where_clause(self, db):
        result = execute_query(db, "SELECT name FROM products WHERE price < 10")
        rows = json.loads(result)
        names = [r["name"] for r in rows]
        assert "Widget" in names
        assert "Doohickey" in names
        assert "Gadget" not in names

    def test_delete_is_blocked(self, db):
        result = execute_query(db, "DELETE FROM customers WHERE id=1")
        assert "Security error" in result
        assert "DELETE" in result

    def test_update_is_blocked(self, db):
        result = execute_query(db, "UPDATE products SET price=0")
        assert "Security error" in result
        assert "UPDATE" in result

    def test_insert_is_blocked(self, db):
        result = execute_query(db, "INSERT INTO customers(name,email) VALUES('X','x@x.com')")
        assert "Security error" in result

    def test_drop_is_blocked(self, db):
        result = execute_query(db, "DROP TABLE customers")
        assert "Security error" in result

    def test_alter_is_blocked(self, db):
        result = execute_query(db, "ALTER TABLE customers ADD COLUMN phone TEXT")
        assert "Security error" in result

    def test_truncate_is_blocked(self, db):
        result = execute_query(db, "TRUNCATE TABLE customers")
        assert "Security error" in result

    def test_create_is_blocked(self, db):
        result = execute_query(db, "CREATE TABLE evil (id INTEGER)")
        assert "Security error" in result

    def test_replace_is_blocked(self, db):
        result = execute_query(db, "REPLACE INTO customers VALUES(1,'X','x@x.com')")
        assert "Security error" in result

    def test_case_insensitive_blocking(self, db):
        result = execute_query(db, "delete from customers")
        assert "Security error" in result

    def test_auto_limit_appended_when_missing(self, db):
        # Insert enough rows to exceed 100 if auto-limit were absent
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE nums (n INTEGER)")
        conn.executemany("INSERT INTO nums VALUES (?)", [(i,) for i in range(200)])
        conn.commit()
        result = execute_query(conn, "SELECT * FROM nums")
        rows = json.loads(result)
        assert len(rows) == 100
        conn.close()

    def test_explicit_limit_is_respected(self, db):
        result = execute_query(db, "SELECT * FROM products LIMIT 2")
        rows = json.loads(result)
        assert len(rows) == 2

    def test_invalid_sql_returns_error_string(self, db):
        result = execute_query(db, "SELECT * FROM nonexistent_table")
        # Should return the sqlite3 error message as a string, not raise
        assert "no such table" in result.lower()
