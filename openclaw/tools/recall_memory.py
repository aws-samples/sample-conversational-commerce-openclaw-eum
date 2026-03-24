#!/usr/bin/env python3
"""
recall_memory.py - Search saved interaction memories.

Calls the Store API instead of connecting to MySQL directly.

Usage:
    python recall_memory.py --interaction_type "refund_request"
    python recall_memory.py --customer_phone "+12125550101"
    python recall_memory.py --search "wrong size"

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer_phone", required=False, default=None)
    parser.add_argument("--interaction_type", required=False, default=None)
    parser.add_argument("--search", required=False, default=None)
    parser.add_argument("--limit", required=False, default=10, type=int)
    args = parser.parse_args()

    try:
        params = {}
        if args.customer_phone:
            params["customer_phone"] = args.customer_phone
        if args.interaction_type:
            params["interaction_type"] = args.interaction_type
        if args.search:
            params["search"] = args.search
        params["limit"] = str(args.limit)

        memories = api_get("/api/memory", params=params)
        print(json.dumps({"memories": memories, "count": len(memories)}))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
