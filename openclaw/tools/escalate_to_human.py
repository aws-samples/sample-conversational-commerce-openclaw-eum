#!/usr/bin/env python3
"""
escalate_to_human.py - Flag a customer conversation for human review and
                        notify the seller via WhatsApp and/or email.

Called by the OpenClaw tool system (Docker sandbox). Writes an escalation
record to the DB, sends a WhatsApp alert to the seller, and optionally
sends an escalation_alert email via SES.

Required environment variables:
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME      (MySQL connection)
    SELLER_PHONE                                 (E.164 WhatsApp number for the store owner)
    WHATSAPP_API_URL                             (WhatsApp Cloud API base URL)
    WHATSAPP_PHONE_NUMBER_ID                     (Sender phone-number ID)
    WHATSAPP_TOKEN                               (System-user access token)

Optional environment variables:
    SELLER_EMAIL           If set, an escalation_alert email is also dispatched via SES.
    SELLER_NAME            Display name in the escalation email (default: "Store Owner")
    AWS_ACCESS_KEY_ID      Required if SELLER_EMAIL is set
    AWS_SECRET_ACCESS_KEY  Required if SELLER_EMAIL is set
    AWS_REGION             Required if SELLER_EMAIL is set
    SES_FROM_EMAIL         Required if SELLER_EMAIL is set
    SES_FROM_NAME          Optional sender display name

Input  (CLI args):
    --reason          <str>   Brief reason for escalation e.g. "payment dispute"  (required)
    --customer_phone  <str>   Customer phone in E.164 format                       (required)
    --summary         <str>   Free-text summary of the conversation so far         (required)

Output (stdout, JSON):
    {
        "success": bool,
        "escalation_id": str,
        "seller_notified": bool
    }
    On error: {"error": "<message>"}
"""

import argparse
import json
import os
import sys
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone

import pymysql


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open a pymysql connection using env-based credentials."""
    try:
        conn = pymysql.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            autocommit=False,
        )
        return conn
    except KeyError as exc:
        raise EnvironmentError(f"Missing required environment variable: {exc}") from exc
    except pymysql.MySQLError as exc:
        raise ConnectionError(f"Database connection failed: {exc}") from exc


# ---------------------------------------------------------------------------
# WhatsApp helper (inline; avoids importing send_customer_reply as a module)
# ---------------------------------------------------------------------------

def _send_whatsapp_text(to: str, body: str) -> bool:
    """
    Send a plain-text WhatsApp message to the seller.

    Returns True on success, False on any API error (escalation itself should
    not fail just because the WhatsApp ping failed).
    """
    required = ("WHATSAPP_API_URL", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TOKEN")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        return False  # Silently skip if WhatsApp is not configured

    api_url = os.environ["WHATSAPP_API_URL"].rstrip("/")
    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    token = os.environ["WHATSAPP_TOKEN"]

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }

    url = f"{api_url}/{phone_number_id}/messages"
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# SES email helper (inline)
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
    This is best-effort; DB record is the authoritative escalation log.
    """
    required = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "SES_FROM_EMAIL"
    )
    if any(not os.environ.get(k) for k in required):
        return False

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return False  # boto3 not available in this sandbox

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
        ses = boto3.client(
            "ses",
            region_name=os.environ["AWS_REGION"],
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        )
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
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def escalate_to_human(
    reason: str,
    customer_phone: str,
    summary: str,
) -> dict:
    """
    Record an escalation and alert the seller.

    Steps:
        1. Insert a row into the `escalations` table (created if absent via
           a CREATE TABLE IF NOT EXISTS guard).
        2. Send a WhatsApp alert to SELLER_PHONE.
        3. Optionally send an email to SELLER_EMAIL if configured.

    Args:
        reason:         Short description of why escalation is needed.
        customer_phone: Customer's E.164 phone number.
        summary:        Summary of the conversation that led to escalation.

    Returns:
        dict with 'success', 'escalation_id', and 'seller_notified'.
    """
    reason = reason.strip()
    customer_phone = customer_phone.strip()
    summary = summary.strip()

    if not reason:
        raise ValueError("reason must not be empty")
    if not customer_phone:
        raise ValueError("customer_phone must not be empty")
    if not summary:
        raise ValueError("summary must not be empty")

    seller_phone = os.environ.get("SELLER_PHONE", "").strip()
    if not seller_phone:
        raise EnvironmentError("Missing required environment variable: SELLER_PHONE")

    escalation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # ---- Persist escalation record ----
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Create the escalations table if it doesn't exist yet.
            # This table is not in the base schema so we ensure it exists here.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS escalations (
                    id           VARCHAR(36)  NOT NULL PRIMARY KEY,
                    customer_phone VARCHAR(20) NOT NULL,
                    reason       TEXT         NOT NULL,
                    summary      TEXT         NOT NULL,
                    status       VARCHAR(20)  NOT NULL DEFAULT 'open',
                    created_at   DATETIME     NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO escalations (id, customer_phone, reason, summary, status, created_at)
                VALUES (%s, %s, %s, %s, 'open', %s)
                """,
                (escalation_id, customer_phone, reason, summary, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # ---- Notify seller via WhatsApp ----
    seller_name = os.environ.get("SELLER_NAME", "Store Owner")
    whatsapp_body = (
        f"[Claw Boutique - Escalation Alert]\n\n"
        f"A customer needs your attention.\n"
        f"Customer: {customer_phone}\n"
        f"Reason: {reason}\n\n"
        f"Summary:\n{summary}\n\n"
        f"Escalation ID: {escalation_id}"
    )
    wa_ok = _send_whatsapp_text(seller_phone, whatsapp_body)

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

    # seller_notified = True if at least one channel succeeded
    seller_notified = wa_ok or email_ok

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
    except (ValueError, EnvironmentError, ConnectionError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
