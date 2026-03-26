#!/usr/bin/env python3
"""
restock_product.py - Restock a product by adding units to its inventory.

Calls the Store API to increase stock for a product matched by name.

Input  (CLI args):
    --product_name  <str>   Product name or partial match (e.g. "Floral Wrap Blouse - Ivory / M")
    --qty           <int>   Number of units to add (default: 20)

Output (stdout, JSON):
    {"success": true, "product_id", "product_name", "qty_added", "new_stock"}
    On error: {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_post


def main():
    parser = argparse.ArgumentParser(description="Restock a product")
    parser.add_argument("--product_name", required=True, help="Product name or partial match")
    parser.add_argument("--qty", type=int, default=20, help="Units to add (default 20)")
    args = parser.parse_args()

    try:
        result = api_post("/api/admin/email-action", {
            "action": "restock",
            "product_name": args.product_name,
            "qty": args.qty,
        })
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
