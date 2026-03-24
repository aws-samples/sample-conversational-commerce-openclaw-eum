#!/usr/bin/env python3
"""
analyze_stock.py - Analyze stock levels and predict reorder needs.

Calls the Store API instead of connecting to MySQL directly.

Usage:
    python analyze_stock.py
    python analyze_stock.py --category tops
    python analyze_stock.py --low_stock_only --threshold 10

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=False, default=None)
    parser.add_argument("--product_id", required=False, default=None, type=int)
    parser.add_argument("--low_stock_only", action="store_true", default=False)
    parser.add_argument("--threshold", type=int, default=10)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    try:
        params = {"days": str(args.days), "threshold": str(args.threshold)}
        if args.category:
            params["category"] = args.category
        if args.low_stock_only:
            params["low_stock_only"] = "true"

        result = api_get("/api/stock/analysis", params=params)

        # If product_id filter requested, filter client-side
        if args.product_id and isinstance(result.get("analysis"), list):
            result["analysis"] = [
                a for a in result["analysis"]
                if a.get("product_id") == args.product_id
            ]
            result["total_products"] = len(result["analysis"])

        print(json.dumps(result))

    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
