#!/usr/bin/env python3
"""
list_products.py - List products with optional filtering by category, size, and color.

Called by the OpenClaw tool system (Docker sandbox). Reads DB credentials
from environment variables and returns a JSON array to stdout.

Input  (CLI args, all optional):
    --category  <str>   e.g. "tops", "bottoms", "accessories"
    --size      <str>   e.g. "S", "M", "L", "XL"
    --color     <str>   e.g. "black", "white", "pink"

Output (stdout, JSON):
    [
        {
            "id": str,
            "name": str,
            "category": str,
            "size": str,
            "color": str,
            "price": float,
            "stock_qty": int
        },
        ...
    ]
    On error: {"error": "<message>"}
"""

import argparse
import json
import os
import sys

import pymysql


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open a pymysql connection using env-based credentials."""
    try:
        conn = pymysql.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
        return conn
    except KeyError as exc:
        raise EnvironmentError(f"Missing required environment variable: {exc}") from exc
    except pymysql.MySQLError as exc:
        raise ConnectionError(f"Database connection failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def list_products(
    category: str | None = None,
    size: str | None = None,
    color: str | None = None,
) -> list[dict]:
    """
    Retrieve products from the database, with optional filtering.

    Args:
        category: Filter by product category (case-insensitive). Optional.
        size:     Filter by size (case-insensitive). Optional.
        color:    Filter by color (case-insensitive). Optional.

    Returns:
        A list of product dicts, each containing id, name, category, size,
        color, price, and stock_qty.

    Raises:
        EnvironmentError: If a required DB env var is missing.
        ConnectionError:  If the DB connection cannot be established.
    """
    # Build WHERE clause dynamically to avoid injecting None comparisons
    conditions: list[str] = []
    params: list[str] = []

    if category:
        conditions.append("LOWER(p.category) = LOWER(%s)")
        params.append(category.strip())
    if size:
        conditions.append("LOWER(p.size) = LOWER(%s)")
        params.append(size.strip())
    if color:
        conditions.append("LOWER(p.color) = LOWER(%s)")
        params.append(color.strip())

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            id,
            name,
            category,
            size,
            color,
            price,
            stock_qty
        FROM products p
        {where_clause}
        ORDER BY category, name
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "size": row["size"],
                "color": row["color"],
                "price": float(row["price"]),
                "stock_qty": int(row["stock_qty"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="List products with optional filters")
    parser.add_argument("--category", default=None, help="Filter by category")
    parser.add_argument("--size", default=None, help="Filter by size")
    parser.add_argument("--color", default=None, help="Filter by color")
    args = parser.parse_args()

    try:
        result = list_products(
            category=args.category,
            size=args.size,
            color=args.color,
        )
        print(json.dumps(result))
    except (EnvironmentError, ConnectionError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
