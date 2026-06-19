#!/usr/bin/env python3
"""
save_memory.py - Save an interaction memory for future reference.

Calls the Store API instead of connecting to MySQL directly.

Usage:
    python save_memory.py \
        --customer_phone "+12125550101" \
        --interaction_type "refund_request" \
        --summary "Customer received wrong size. Issued full refund." \
        --resolution "Refund processed, replacement shipped next day" \
        --tags '["wrong_item","refund","resolved"]'

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_post


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer_phone", required=False, default=None)
    parser.add_argument("--interaction_type", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--resolution", required=False, default=None)
    parser.add_argument("--tags", required=False, default="[]")
    args = parser.parse_args()

    try:
        tags = json.loads(args.tags) if isinstance(args.tags, str) else args.tags
    except json.JSONDecodeError:
        tags = []

    try:
        body = {
            "customer_phone": args.customer_phone,
            "interaction_type": args.interaction_type,
            "summary": args.summary,
            "resolution": args.resolution,
            "tags": tags,
        }
        result = api_post("/api/memory", body)
        print(json.dumps({
            "success": True,
            "memory_id": result.get("id"),
            "interaction_type": args.interaction_type,
        }))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
