#!/usr/bin/env python3
"""
create_order.py - Create a new order for a customer.

Calls the Store API instead of connecting to MySQL directly.

Input  (CLI args):
    --customer_phone  <str>   E.164 format e.g. "+639171234567"  (required)
    --customer_name   <str>                                       (required)
    --customer_email  <str>                                       (required)
    --items           <JSON>  '[{"product_id": 1, "qty": 2}]'    (required)

Output (stdout, JSON):
    {"order_id": int, "total": float, "confirmation_sent": false}
    On error: {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_post


def validate_items(items_raw: str) -> list[dict]:
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
        validated.append({"product_id": int(item["product_id"]), "qty": qty})

    return validated


def main():
    parser = argparse.ArgumentParser(description="Create a new customer order")
    parser.add_argument("--customer_phone", required=True, help="E.164 phone number")
    parser.add_argument("--customer_name", required=True, help="Customer full name")
    parser.add_argument("--customer_email", required=True, help="Customer email address")
    parser.add_argument(
        "--items",
        required=True,
        help='JSON array of {product_id, qty} e.g. \'[{"product_id":1,"qty":2}]\'',
    )
    args = parser.parse_args()

    try:
        items = validate_items(args.items)
        result = api_post("/api/orders", {
            "customer_name": args.customer_name,
            "customer_email": args.customer_email,
            "customer_phone": args.customer_phone,
            "items": items,
        })
        result["confirmation_sent"] = False
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
