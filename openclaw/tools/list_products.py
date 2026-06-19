#!/usr/bin/env python3
"""
list_products.py - List products with optional filtering by category, size, and color.

Calls the Store API instead of connecting to MySQL directly.

Input  (CLI args, all optional):
    --category  <str>   e.g. "tops", "bottoms", "accessories"
    --size      <str>   e.g. "S", "M", "L", "XL"
    --color     <str>   e.g. "black", "white", "pink"

Output (stdout, JSON):
    [{"id", "name", "category", "size", "color", "price", "stock_qty"}, ...]
    On error: {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get


def main():
    parser = argparse.ArgumentParser(description="List products with optional filters")
    parser.add_argument("--category", default=None, help="Filter by category")
    parser.add_argument("--size", default=None, help="Filter by size")
    parser.add_argument("--color", default=None, help="Filter by color")
    args = parser.parse_args()

    try:
        params = {}
        if args.category:
            params["category"] = args.category
        if args.size:
            params["size"] = args.size
        if args.color:
            params["color"] = args.color

        result = api_get("/api/products", params=params or None)
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
