#!/usr/bin/env python3
"""
lookup_order.py - Retrieve full order details by order ID.

Calls the Store API instead of connecting to MySQL directly.

Input  (CLI args): --order_id <id>
Output (stdout, JSON):
    {"id", "status", "items": [...], "customer": {...}, "total", "shipped_date", "tracking"}
    On error: {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get


def main():
    parser = argparse.ArgumentParser(description="Look up an order by ID")
    parser.add_argument("--order_id", required=True, help="Order ID to retrieve")
    args = parser.parse_args()

    try:
        result = api_get(f"/api/orders/{args.order_id}")
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
