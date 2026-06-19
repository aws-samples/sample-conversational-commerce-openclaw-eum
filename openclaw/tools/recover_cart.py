#!/usr/bin/env python3
"""
recover_cart.py - Find abandoned carts and generate recovery messages.

Calls the Store API instead of connecting to MySQL directly.

Usage:
    python recover_cart.py --customer_phone "+12125550101"
    python recover_cart.py --check_all --hours 2

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer_phone", required=False, default=None)
    parser.add_argument("--check_all", action="store_true", default=False)
    parser.add_argument("--hours", type=int, default=2,
                        help="Hours since last activity to consider cart abandoned")
    args = parser.parse_args()

    if not args.customer_phone and not args.check_all:
        print(json.dumps({"error": "Provide --customer_phone or --check_all"}))
        sys.exit(1)

    try:
        params = {"hours": str(args.hours)}
        if args.customer_phone:
            params["customer_phone"] = args.customer_phone

        carts = api_get("/api/carts/abandoned", params=params)

        if not carts:
            print(json.dumps({
                "success": True,
                "abandoned_carts": [],
                "count": 0,
                "message": "No abandoned carts found"
            }))
            return

        results = []
        for cart in carts:
            cart_items = cart.get("cart_json", [])
            if isinstance(cart_items, str):
                cart_items = json.loads(cart_items)

            customer_name = cart.get("customer_name") or "there"
            item_count = len(cart_items)

            # Generate personalized recovery message
            first_item = "those items"
            if cart_items and isinstance(cart_items[0], dict):
                first_item = cart_items[0].get("name", "those items")

            if item_count == 1:
                message = (
                    f"Hey {customer_name}! I noticed you were looking at "
                    f"the {first_item}. It's still in your cart and we're "
                    f"holding your size. I can offer you free shipping if "
                    f"you finish the order in the next hour!"
                )
            else:
                message = (
                    f"Hey {customer_name}! You left {item_count} items in "
                    f"your cart, including the {first_item}. They're still "
                    f"available! Complete your order now and I'll throw in "
                    f"free shipping."
                )

            results.append({
                "customer_phone": cart.get("customer_phone"),
                "customer_name": customer_name,
                "cart_items": cart_items,
                "recovery_message": message,
                "last_updated": cart.get("last_updated"),
            })

        print(json.dumps({
            "success": True,
            "abandoned_carts": results,
            "count": len(results),
        }))

    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
