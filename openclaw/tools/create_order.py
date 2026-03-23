#!/usr/bin/env python3
"""
create_order.py - Create a new order for a customer, upserting the customer record
                  if they do not already exist.

Called by the OpenClaw tool system (Docker sandbox). Reads DB credentials
from environment variables and returns a single JSON object to stdout.

Input  (CLI args):
    --customer_phone  <str>   E.164 format e.g. "+639171234567"  (required)
    --customer_name   <str>                                       (required)
    --customer_email  <str>                                       (required)
    --items           <JSON>  '[{"product_id": "p1", "qty": 2}]' (required)

Output (stdout, JSON):
    {
        "order_id": str,
        "total": float,
        "confirmation_sent": bool   # always false here; send_email handles that
    }
    On error: {"error": "<message>"}

Notes:
    - Wraps the full operation in a single transaction; rolls back on any failure.
    - Deducts stock from the products table atomically.
    - Raises an error if any product is out of stock or does not exist.
    - Does NOT send confirmation email/SMS; call send_email / send_customer_reply
      separately after receiving the order_id.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import pymysql


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open a pymysql connection using env-based credentials (autocommit=False)."""
    try:
        conn = pymysql.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            autocommit=False,
        )
        return conn
    except KeyError as exc:
        raise EnvironmentError(f"Missing required environment variable: {exc}") from exc
    except pymysql.MySQLError as exc:
        raise ConnectionError(f"Database connection failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_items(items_raw: str) -> list[dict]:
    """
    Parse and validate the JSON items argument.

    Expected format: [{"product_id": str, "qty": int}, ...]

    Raises:
        ValueError: If the JSON is malformed or any item is invalid.
    """
    try:
        items = json.loads(items_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"'items' is not valid JSON: {exc}") from exc

    if not isinstance(items, list) or not items:
        raise ValueError("'items' must be a non-empty JSON array")

    validated = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Item at index {i} must be an object")
        if "product_id" not in item or "qty" not in item:
            raise ValueError(f"Item at index {i} must have 'product_id' and 'qty'")
        try:
            qty = int(item["qty"])
        except (TypeError, ValueError):
            raise ValueError(f"Item at index {i}: 'qty' must be an integer")
        if qty < 1:
            raise ValueError(f"Item at index {i}: 'qty' must be >= 1")
        validated.append({"product_id": str(item["product_id"]).strip(), "qty": qty})

    return validated


def validate_email(email: str) -> str:
    """Basic email sanity check (not RFC-5322 full validation)."""
    email = email.strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError(f"Invalid email address: '{email}'")
    return email


def validate_phone(phone: str) -> str:
    """Ensure phone starts with '+' and has only digits after that."""
    phone = phone.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        raise ValueError(
            f"Invalid phone number '{phone}'. Must be E.164 format e.g. +639171234567"
        )
    return phone


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def create_order(
    customer_phone: str,
    customer_name: str,
    customer_email: str,
    items: list[dict],
) -> dict:
    """
    Upsert customer, create the order record, insert line items, and deduct stock.

    Args:
        customer_phone: E.164 phone number.
        customer_name:  Full name of the customer.
        customer_email: Email address of the customer.
        items:          List of dicts with 'product_id' and 'qty'.

    Returns:
        dict with 'order_id', 'total', and 'confirmation_sent'.

    Raises:
        ValueError:      If any product is not found or insufficient stock.
        EnvironmentError / ConnectionError: On DB setup issues.
    """
    # Validate inputs
    customer_phone = validate_phone(customer_phone)
    customer_email = validate_email(customer_email)
    customer_name = customer_name.strip()
    if not customer_name:
        raise ValueError("customer_name must not be empty")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # ---- Upsert customer (match on phone as unique key) ----
            cur.execute(
                "SELECT id FROM customers WHERE phone = %s LIMIT 1",
                (customer_phone,),
            )
            existing = cur.fetchone()

            now = datetime.now(timezone.utc)

            if existing:
                customer_id = existing["id"]
                # Update name/email in case they changed
                cur.execute(
                    "UPDATE customers SET name = %s, email = %s WHERE id = %s",
                    (customer_name, customer_email, customer_id),
                )
            else:
                customer_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO customers (id, phone, email, name, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (customer_id, customer_phone, customer_email, customer_name, now),
                )

            # ---- Lock product rows and validate stock ----
            product_ids = [item["product_id"] for item in items]
            placeholders = ", ".join(["%s"] * len(product_ids))
            cur.execute(
                f"SELECT id, price, stock_qty FROM products WHERE id IN ({placeholders}) FOR UPDATE",
                product_ids,
            )
            products_found = {row["id"]: row for row in cur.fetchall()}

            total = 0.0
            enriched_items = []

            for item in items:
                pid = item["product_id"]
                qty = item["qty"]

                if pid not in products_found:
                    raise ValueError(f"Product '{pid}' not found")

                product = products_found[pid]
                available = int(product["stock_qty"])

                if available < qty:
                    raise ValueError(
                        f"Insufficient stock for product '{pid}': "
                        f"requested {qty}, available {available}"
                    )

                unit_price = float(product["price"])
                total += unit_price * qty
                enriched_items.append(
                    {"product_id": pid, "qty": qty, "unit_price": unit_price}
                )

            # ---- Create order record ----
            order_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO orders (id, customer_id, status, total, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, customer_id, "pending", round(total, 2), now),
            )

            # ---- Insert order_items and decrement stock ----
            for item in enriched_items:
                item_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO order_items (id, order_id, product_id, qty, unit_price)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        item_id,
                        order_id,
                        item["product_id"],
                        item["qty"],
                        item["unit_price"],
                    ),
                )
                cur.execute(
                    "UPDATE products SET stock_qty = stock_qty - %s WHERE id = %s",
                    (item["qty"], item["product_id"]),
                )

        # Commit only after all operations succeed
        conn.commit()

        return {
            "order_id": order_id,
            "total": round(total, 2),
            "confirmation_sent": False,  # Caller should invoke send_email next
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Create a new customer order")
    parser.add_argument("--customer_phone", required=True, help="E.164 phone number")
    parser.add_argument("--customer_name", required=True, help="Customer full name")
    parser.add_argument("--customer_email", required=True, help="Customer email address")
    parser.add_argument(
        "--items",
        required=True,
        help='JSON array of {product_id, qty} e.g. \'[{"product_id":"p1","qty":2}]\'',
    )
    args = parser.parse_args()

    try:
        items = validate_items(args.items)
        result = create_order(
            customer_phone=args.customer_phone,
            customer_name=args.customer_name,
            customer_email=args.customer_email,
            items=items,
        )
        print(json.dumps(result))
    except (ValueError, EnvironmentError, ConnectionError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
