#!/usr/bin/env python3
"""
escalate_to_human.py - Flag a customer conversation for human review and
                        notify the seller via Telegram.

Calls the Store API to persist the escalation record, then sends
a Telegram notification via the OpenClaw agent-bridge.

Required environment variables:
    STORE_API_URL                                (Store API base URL)
    OPENCLAW_BRIDGE_URL                          (agent-bridge URL, e.g. http://localhost:18790)
    OPENCLAW_BRIDGE_TOKEN                        (auth token for agent-bridge)

Optional environment variables:
    STORE_API_KEY          API key for Store API authentication
    SELLER_NAME            Display name in alerts (default: "Store Owner")

Input  (CLI args):
    --reason          <str>   Brief reason for escalation e.g. "payment dispute"  (required)
    --customer_phone  <str>   Customer phone in E.164 format                       (required)
    --summary         <str>   Free-text summary of the conversation so far         (required)

Output (stdout, JSON):
    {
        "success": bool,
        "escalation_id": int,
        "seller_notified": bool    # True if Telegram alert was delivered
    }
    On error: {"error": "<message>"}
"""

import argparse
import json
import os
import sys

from _api import api_post


# ---------------------------------------------------------------------------
# Telegram helper (via agent-bridge)
# ---------------------------------------------------------------------------

def _send_telegram_alert(body: str) -> bool:
    """
    Send a plain-text alert to the seller via the OpenClaw agent-bridge,
    which delivers it through Telegram.
    Returns True on success, False on any error.
    """
    bridge_url = os.environ.get("OPENCLAW_BRIDGE_URL", "").strip()
    bridge_token = os.environ.get("OPENCLAW_BRIDGE_TOKEN", "").strip()
    if not bridge_url:
        return False

    import urllib.request

    try:
        req = urllib.request.Request(
            f"{bridge_url}/notify",
            data=json.dumps({"message": body}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bridge_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def escalate_to_human(
    reason: str,
    customer_phone: str,
    summary: str,
) -> dict:
    reason = reason.strip()
    customer_phone = customer_phone.strip()
    summary = summary.strip()

    if not reason:
        raise ValueError("reason must not be empty")
    if not customer_phone:
        raise ValueError("customer_phone must not be empty")
    if not summary:
        raise ValueError("summary must not be empty")

    # ---- Notify seller via Telegram (agent-bridge) ----
    seller_name = os.environ.get("SELLER_NAME", "Store Owner")
    telegram_body = (
        f"[Claw Boutique - Escalation Alert]\n\n"
        f"A customer needs your attention.\n"
        f"Customer: {customer_phone}\n"
        f"Reason: {reason}\n\n"
        f"Summary:\n{summary}"
    )
    tg_ok = _send_telegram_alert(telegram_body)

    # ---- Persist escalation record via Store API ----
    api_result = api_post("/api/escalations", {
        "customer_phone": customer_phone,
        "reason": reason,
        "summary": summary,
        "seller_notified": tg_ok,
    })

    escalation_id = api_result.get("escalation_id")

    return {
        "success": True,
        "escalation_id": escalation_id,
        "seller_notified": tg_ok,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Escalate a customer conversation to a human agent"
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Brief reason for escalation e.g. 'payment dispute'",
    )
    parser.add_argument(
        "--customer_phone",
        required=True,
        help="Customer phone in E.164 format",
    )
    parser.add_argument(
        "--summary",
        required=True,
        help="Summary of the conversation that led to the escalation",
    )
    args = parser.parse_args()

    try:
        result = escalate_to_human(
            reason=args.reason,
            customer_phone=args.customer_phone,
            summary=args.summary,
        )
        print(json.dumps(result))
    except (ValueError, EnvironmentError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
