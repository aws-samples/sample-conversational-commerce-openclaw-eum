#!/usr/bin/env python3
"""
escalate_to_human.py - Flag a customer conversation for human review and
                        notify the seller via Telegram and/or email.

Calls the Store API to persist the escalation record, then sends
notifications via the OpenClaw agent-bridge (Telegram) and SES (email).

Required environment variables:
    STORE_API_URL                                (Store API base URL)
    OPENCLAW_BRIDGE_URL                          (agent-bridge URL, e.g. http://localhost:18790)
    OPENCLAW_BRIDGE_TOKEN                        (auth token for agent-bridge)

Optional environment variables:
    STORE_API_KEY          API key for Store API authentication
    SELLER_EMAIL           If set, an escalation_alert email is also dispatched via SES.
    SELLER_NAME            Display name in the escalation email (default: "Store Owner")
    SES_FROM_EMAIL         Required if SELLER_EMAIL is set
    SES_FROM_NAME          Optional sender display name

Input  (CLI args):
    --reason          <str>   Brief reason for escalation e.g. "payment dispute"  (required)
    --customer_phone  <str>   Customer phone in E.164 format                       (required)
    --summary         <str>   Free-text summary of the conversation so far         (required)

Output (stdout, JSON):
    {
        "success": bool,
        "escalation_id": int,
        "seller_notified": bool
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
# SES email helper
# ---------------------------------------------------------------------------

def _send_escalation_email(
    seller_email: str,
    seller_name: str,
    customer_phone: str,
    reason: str,
    summary: str,
) -> bool:
    """
    Send an escalation_alert email via SES.
    Returns True on success, False if env vars are absent or SES call fails.
    """
    required = ("AWS_REGION", "SES_FROM_EMAIL")
    if any(not os.environ.get(k) for k in required):
        return False

    try:
        import boto3
    except ImportError:
        return False

    from_addr = os.environ["SES_FROM_EMAIL"]
    from_name = os.environ.get("SES_FROM_NAME", "")
    sender = f"{from_name} <{from_addr}>" if from_name else from_addr

    subject = "[Action Required] Customer escalation from Claw Boutique AI"

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Escalation Alert</title></head>
<body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
  <h2 style="color:#c0392b">Claw Boutique &mdash; Escalation Alert</h2>
  <p>Hi {seller_name},</p>
  <p>A customer conversation requires your attention.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee"><strong>Customer Phone</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{customer_phone}</td>
    </tr>
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee"><strong>Reason</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{reason}</td>
    </tr>
    <tr>
      <td style="padding:8px"><strong>Summary</strong></td>
      <td style="padding:8px">{summary}</td>
    </tr>
  </table>
  <p style="margin-top:20px;color:#c0392b;font-weight:bold">
    Please follow up with the customer as soon as possible.
  </p>
  <p style="color:#888;font-size:12px">OpenClaw AI &mdash; Claw Boutique automated assistant</p>
</body>
</html>"""

    text_body = (
        f"Hi {seller_name},\n\n"
        f"A customer conversation requires your attention.\n\n"
        f"Customer Phone: {customer_phone}\n"
        f"Reason: {reason}\n"
        f"Summary:\n{summary}\n\n"
        f"Please follow up as soon as possible.\n\n"
        f"-- OpenClaw AI / Claw Boutique"
    )

    try:
        ses = boto3.client("ses", region_name=os.environ["AWS_REGION"])
        ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [seller_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        return True
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

    # ---- Optionally notify via email ----
    seller_email = os.environ.get("SELLER_EMAIL", "").strip()
    email_ok = False
    if seller_email:
        email_ok = _send_escalation_email(
            seller_email=seller_email,
            seller_name=seller_name,
            customer_phone=customer_phone,
            reason=reason,
            summary=summary,
        )

    seller_notified = tg_ok or email_ok

    # ---- Persist escalation record via Store API ----
    api_result = api_post("/api/escalations", {
        "customer_phone": customer_phone,
        "reason": reason,
        "summary": summary,
        "seller_notified": seller_notified,
    })

    escalation_id = api_result.get("escalation_id")

    return {
        "success": True,
        "escalation_id": escalation_id,
        "seller_notified": seller_notified,
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
