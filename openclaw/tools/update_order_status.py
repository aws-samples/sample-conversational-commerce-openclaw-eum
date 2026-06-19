#!/usr/bin/env python3
"""
update_order_status.py - Update the status of an existing order.

Calls the Store API instead of connecting to MySQL directly.

Input  (CLI args):
    --order_id      <str>   (required)
    --new_status    <str>   One of: pending, confirmed, shipped, delivered, cancelled
    --tracking_url  <str>   Required when new_status is "shipped"

Output (stdout, JSON):
    {"success": true, "status_before": str, "status_after": str}
    On error: {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_patch

VALID_STATUSES = {"pending", "confirmed", "shipped", "delivered", "cancelled"}


def main():
    parser = argparse.ArgumentParser(description="Update the status of an order")
    parser.add_argument("--order_id", required=True, help="Order ID to update")
    parser.add_argument("--new_status", required=True,
                        help=f"New status. One of: {', '.join(sorted(VALID_STATUSES))}")
    parser.add_argument("--tracking_url", default=None,
                        help="Shipping tracking URL (required when new_status=shipped)")
    args = parser.parse_args()

    try:
        body = {"new_status": args.new_status}
        if args.tracking_url:
            body["tracking_url"] = args.tracking_url

        result = api_patch(f"/api/orders/{args.order_id}/status", body)
        # Normalize response to match expected output
        print(json.dumps({
            "success": True,
            "status_before": result.get("status_before", "unknown"),
            "status_after": result.get("status", args.new_status),
        }))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
