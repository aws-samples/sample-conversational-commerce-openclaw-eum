#!/usr/bin/env python3
"""
apologize_customer.py - List or resolve customer escalations via WhatsApp apology.

Modes:
    --list              List all unresolved escalations (use this first).
    --escalation_id N   Send apology for a specific escalation by ID.
    (no flags)          Send apology for the most recent unresolved escalation.

Output (stdout, JSON):
    --list mode:   {"escalations": [...], "count": N}
    resolve mode:  {"success": true, "escalation_id": N, "customer_phone": "...", ...}
    On error:      {"error": "<message>"}

Required env vars: STORE_API_URL (and optionally STORE_API_KEY)
"""

import argparse
import json
import sys

from _api import api_get, api_post


def main():
    parser = argparse.ArgumentParser(description="List or resolve customer escalations")
    parser.add_argument("--list", action="store_true", help="List unresolved escalations")
    parser.add_argument("--escalation_id", type=int, default=None, help="Resolve a specific escalation by ID")
    parser.add_argument("--customer_phone", default=None, help="Filter by customer phone (optional)")
    args = parser.parse_args()

    try:
        # Get unresolved escalations
        escalations = api_get("/api/escalations", {"resolved": "false"})

        if not escalations:
            print(json.dumps({"error": "No unresolved escalations found."}))
            sys.exit(1)

        # List mode: show all unresolved escalations
        if args.list:
            items = []
            for e in escalations:
                items.append({
                    "id": e["id"],
                    "customer_phone": e.get("customer_phone", ""),
                    "reason": e.get("reason", ""),
                    "summary": e.get("summary", ""),
                    "created_at": e.get("created_at", ""),
                })
            print(json.dumps({"escalations": items, "count": len(items)}))
            return

        # Resolve mode: pick the escalation to apologize for
        if args.escalation_id:
            matching = [e for e in escalations if e["id"] == args.escalation_id]
            if not matching:
                print(json.dumps({"error": f"Escalation #{args.escalation_id} not found or already resolved."}))
                sys.exit(1)
            escalation = matching[0]
        elif args.customer_phone:
            phone = args.customer_phone.strip()
            matching = [e for e in escalations if e.get("customer_phone") == phone]
            if not matching:
                print(json.dumps({"error": f"No unresolved escalation for {phone}"}))
                sys.exit(1)
            escalation = matching[0]
        else:
            # Default: most recent (API returns newest first)
            escalation = escalations[0]

        esc_id = escalation["id"]
        customer_phone = escalation.get("customer_phone", "unknown")
        reason = escalation.get("reason", "")
        summary = escalation.get("summary", "")

        # Send apology and resolve via Store API
        result = api_post(f"/api/escalations/{esc_id}/send-apology", {})

        print(json.dumps({
            "success": True,
            "escalation_id": esc_id,
            "customer_phone": customer_phone,
            "reason": reason,
            "summary": summary,
            "api_response": result,
            "message": f"WhatsApp apology sent to {customer_phone}. Escalation #{esc_id} resolved.",
        }))

    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
