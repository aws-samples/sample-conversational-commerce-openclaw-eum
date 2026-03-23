#!/usr/bin/env python3
"""
lookup_order.py - Retrieve full order details by order ID.

Called by the OpenClaw tool system (Docker sandbox). Reads DB credentials
from environment variables and returns a single JSON object to stdout.

Input  (CLI args or env): --order_id <id>
Output (stdout, JSON):
    {
        "id": str,
        "status": str,
        "items": [{"product_id": str, "name": str, "qty": int, "unit_price": float}],
        "customer": {"id": str, "name": str, "phone": str, "email": str},
        "total": float,
        "shipped_date": str | null,   # ISO-8601
        "tracking": str | null
    }
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

def lookup_order(order_id: str) -> dict:
    """
    Fetch a single order and all related data from the database.

    Args:
        order_id: Primary key of the order to retrieve.

    Returns:
        A dict suitable for JSON serialisation containing order details,
        customer info, line items, and shipping info.

    Raises:
        ValueError: If order_id is empty or the order does not exist.
        ConnectionError: If the DB connection cannot be established.
    """
    if not order_id or not str(order_id).strip():
        raise ValueError("order_id must be a non-empty string")

    order_id = str(order_id).strip()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # ---- Fetch order + customer in a single join ----
            cur.execute(
                """
                SELECT
                    o.id            AS order_id,
                    o.status,
                    o.total,
                    o.created_at,
                    o.shipped_at,
                    o.tracking_url,
                    c.id            AS customer_id,
                    c.name          AS customer_name,
                    c.phone         AS customer_phone,
                    c.email         AS customer_email
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.id = %s
                LIMIT 1
                """,
                (order_id,),
            )
            row = cur.fetchone()

        if not row:
            raise ValueError(f"No order found with id '{order_id}'")

        with conn.cursor() as cur:
            # ---- Fetch line items ----
            cur.execute(
                """
                SELECT
                    oi.product_id,
                    p.name,
                    oi.qty,
                    oi.unit_price
                FROM order_items oi
                JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                """,
                (order_id,),
            )
            items = cur.fetchall()

        # ---- Serialise dates to ISO strings ----
        shipped_date = (
            row["shipped_at"].isoformat() if row["shipped_at"] else None
        )

        return {
            "id": row["order_id"],
            "status": row["status"],
            "items": [
                {
                    "product_id": item["product_id"],
                    "name": item["name"],
                    "qty": item["qty"],
                    "unit_price": float(item["unit_price"]),
                }
                for item in items
            ],
            "customer": {
                "id": row["customer_id"],
                "name": row["customer_name"],
                "phone": row["customer_phone"],
                "email": row["customer_email"],
            },
            "total": float(row["total"]),
            "shipped_date": shipped_date,
            "tracking": row["tracking_url"],
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Look up an order by ID")
    parser.add_argument("--order_id", required=True, help="Order ID to retrieve")
    args = parser.parse_args()

    try:
        result = lookup_order(args.order_id)
        print(json.dumps(result))
    except (ValueError, EnvironmentError, ConnectionError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
