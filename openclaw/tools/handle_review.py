#!/usr/bin/env python3
"""
handle_review.py - Process a customer review and take appropriate action.

Calls the Store API instead of connecting to MySQL directly.

For 4-5 star reviews: sends a personalized thank-you WhatsApp message.
For 1-2 star reviews: escalates to seller with a drafted apology response.
For 3 star reviews: sends a gentle follow-up asking how to improve.

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_post


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer_phone", required=True)
    parser.add_argument("--customer_name", required=True)
    parser.add_argument("--rating", required=True, type=int, choices=[1, 2, 3, 4, 5])
    parser.add_argument("--review_text", required=True)
    parser.add_argument("--order_id", required=False, default=None, type=int)
    args = parser.parse_args()

    try:
        api_result = api_post("/api/reviews", {
            "customer_phone": args.customer_phone,
            "customer_name": args.customer_name,
            "rating": args.rating,
            "review_text": args.review_text,
            "order_id": args.order_id,
        })

        review_id = api_result.get("review_id")
        action = api_result.get("action")

        if args.rating >= 4:
            escalate = False
            drafted_response = (
                f"Hi {args.customer_name}! Thank you so much for the wonderful "
                f"{args.rating}-star review! We're thrilled you love your purchase. "
                f"Can't wait to see you shop with us again!"
            )
        elif args.rating == 3:
            escalate = False
            drafted_response = (
                f"Hi {args.customer_name}, thank you for your feedback! We'd love "
                f"to know how we can make your experience even better. Is there "
                f"anything specific we could improve?"
            )
        else:
            escalate = True
            drafted_response = (
                f"Hi {args.customer_name}, I'm really sorry to hear about your "
                f"experience. We take every review seriously and I'd love to make "
                f"this right for you. Could you share more details about what went "
                f"wrong so we can fix it immediately?"
            )

        result = {
            "success": True,
            "review_id": review_id,
            "rating": args.rating,
            "action": action or ("auto_thank" if args.rating >= 4 else "follow_up" if args.rating == 3 else "escalate_to_seller"),
            "escalate_to_seller": escalate,
            "drafted_response": drafted_response,
            "customer_phone": args.customer_phone,
            "customer_name": args.customer_name,
        }

        if escalate:
            result["seller_alert"] = (
                f"REVIEW ALERT: {args.customer_name} ({args.customer_phone}) "
                f"left a {args.rating}-star review"
                f"{' for order #' + str(args.order_id) if args.order_id else ''}: "
                f'"{args.review_text}"\n\n'
                f"Drafted response ready to send. Review ID: {review_id}"
            )

        print(json.dumps(result))

    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
