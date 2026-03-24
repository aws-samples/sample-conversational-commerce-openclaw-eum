#!/usr/bin/env python3
"""
send_email.py - Send a transactional email via Amazon SES (SendEmail API).

Called by the OpenClaw tool system (Docker sandbox). Reads AWS credentials
and sender config from environment variables, renders an inline template,
and dispatches via boto3.

Required environment variables:
    AWS_ACCESS_KEY_ID       AWS IAM credentials with ses:SendEmail permission
    AWS_SECRET_ACCESS_KEY
    AWS_REGION              SES region e.g. "ap-southeast-1"
    SES_FROM_EMAIL          Verified sender address e.g. "orders@clawboutique.ph"
    SES_FROM_NAME           Display name  e.g. "Claw Boutique"  (optional, defaults to SES_FROM_EMAIL)

Input  (CLI args):
    --recipient_email  <str>   Destination address                           (required)
    --template_name    <str>   One of: order_confirmation, order_shipped,
                                        escalation_alert                     (required)
    --variables        <JSON>  '{"order_id": "x", "customer_name": "y"}'    (required)

Output (stdout, JSON):
    {
        "success": bool,
        "email_id": str | null     # SES MessageId on success
    }
    On error: {"error": "<message>"}

Template variable reference:
    order_confirmation:
        customer_name, order_id, items_summary, total, shop_url
    order_shipped:
        customer_name, order_id, tracking_url, carrier
    escalation_alert:
        customer_phone, reason, summary, seller_name
"""

import argparse
import json
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import boto3
from botocore.exceptions import BotoCoreError, ClientError


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict] = {
    "order_confirmation": {
        "subject": "Your Claw Boutique order #{order_id} is confirmed!",
        "html": """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Order Confirmed</title></head>
<body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
  <h2 style="color:#c0392b">Claw Boutique</h2>
  <p>Hi {customer_name},</p>
  <p>We've received your order and it's being prepared with love!</p>
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee"><strong>Order ID</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">#{order_id}</td>
    </tr>
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee"><strong>Items</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{items_summary}</td>
    </tr>
    <tr>
      <td style="padding:8px"><strong>Total</strong></td>
      <td style="padding:8px">PHP {total}</td>
    </tr>
  </table>
  <p style="margin-top:20px">
    Track your order or browse our latest drops at
    <a href="{shop_url}" style="color:#c0392b">{shop_url}</a>
  </p>
  <p>Thank you for shopping with us!</p>
  <p style="color:#888;font-size:12px">Claw Boutique &mdash; Questions? Message us on WhatsApp.</p>
</body>
</html>""",
        "text": (
            "Hi {customer_name},\n\n"
            "Your Claw Boutique order #{order_id} has been confirmed!\n\n"
            "Items: {items_summary}\n"
            "Total: PHP {total}\n\n"
            "Shop: {shop_url}\n\n"
            "Thank you for shopping with us!\n"
            "Claw Boutique"
        ),
    },

    "order_shipped": {
        "subject": "Your Claw Boutique order #{order_id} is on its way!",
        "html": """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Order Shipped</title></head>
<body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
  <h2 style="color:#c0392b">Claw Boutique</h2>
  <p>Hi {customer_name},</p>
  <p>Great news &mdash; your order <strong>#{order_id}</strong> has been shipped!</p>
  <table style="width:100%;border-collapse:collapse">
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee"><strong>Carrier</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{carrier}</td>
    </tr>
    <tr>
      <td style="padding:8px"><strong>Tracking</strong></td>
      <td style="padding:8px">
        <a href="{tracking_url}" style="color:#c0392b">{tracking_url}</a>
      </td>
    </tr>
  </table>
  <p style="margin-top:20px">
    If you have any questions, just reply to this email or message us on WhatsApp.
  </p>
  <p style="color:#888;font-size:12px">Claw Boutique</p>
</body>
</html>""",
        "text": (
            "Hi {customer_name},\n\n"
            "Your Claw Boutique order #{order_id} has been shipped!\n\n"
            "Carrier: {carrier}\n"
            "Tracking: {tracking_url}\n\n"
            "Questions? Message us on WhatsApp.\n"
            "Claw Boutique"
        ),
    },

    "escalation_alert": {
        "subject": "[Action Required] Customer escalation from Claw Boutique AI",
        "html": """\
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
</html>""",
        "text": (
            "Hi {seller_name},\n\n"
            "A customer conversation requires your attention.\n\n"
            "Customer Phone: {customer_phone}\n"
            "Reason: {reason}\n"
            "Summary:\n{summary}\n\n"
            "Please follow up with the customer as soon as possible.\n\n"
            "-- OpenClaw AI / Claw Boutique"
        ),
    },
}

VALID_TEMPLATES = set(TEMPLATES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_ses_client():
    """Build a boto3 SES client using the default credential chain or explicit keys."""
    region = os.environ.get("AWS_REGION", "us-east-1")

    # Use explicit credentials if provided, otherwise fall back to default chain (IAM role, etc.)
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if access_key and secret_key:
        return boto3.client(
            "ses",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    return boto3.client("ses", region_name=region)


def render_template(template_key: str, variables: dict) -> tuple[str, str, str]:
    """
    Render subject, HTML body, and plain-text body for the given template.

    Args:
        template_key: One of the VALID_TEMPLATES keys.
        variables:    Dict of substitution variables.

    Returns:
        Tuple of (subject, html_body, text_body).

    Raises:
        ValueError: If template_key is unknown or a required variable is missing.
    """
    if template_key not in TEMPLATES:
        raise ValueError(
            f"Unknown template '{template_key}'. Valid options: {', '.join(sorted(VALID_TEMPLATES))}"
        )

    tmpl = TEMPLATES[template_key]

    try:
        subject = tmpl["subject"].format(**variables)
        html_body = tmpl["html"].format(**variables)
        text_body = tmpl["text"].format(**variables)
    except KeyError as exc:
        raise ValueError(
            f"Template '{template_key}' requires variable {exc} which was not provided"
        ) from exc

    return subject, html_body, text_body


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def send_email(
    recipient_email: str,
    template_name: str,
    variables: dict,
) -> dict:
    """
    Render a template and send the email via Amazon SES.

    Args:
        recipient_email: Destination email address.
        template_name:   One of: order_confirmation, order_shipped, escalation_alert.
        variables:       Dict of template substitution values.

    Returns:
        dict with 'success' (bool) and 'email_id' (str | None).

    Raises:
        ValueError:      On bad input or unknown template.
        EnvironmentError / RuntimeError: On config or SES API issues.
    """
    recipient_email = recipient_email.strip()
    if "@" not in recipient_email:
        raise ValueError(f"Invalid recipient_email: '{recipient_email}'")

    from_name = os.environ.get("SES_FROM_NAME", "")
    from_addr = os.environ.get("SES_FROM_EMAIL", "")
    if not from_addr:
        raise EnvironmentError("Missing required environment variable: SES_FROM_EMAIL")

    sender = f"{from_name} <{from_addr}>" if from_name else from_addr

    subject, html_body, text_body = render_template(template_name, variables)

    ses = get_ses_client()

    try:
        response = ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        raise RuntimeError(f"SES ClientError [{code}]: {msg}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"SES BotoCoreError: {exc}") from exc

    return {
        "success": True,
        "email_id": response.get("MessageId"),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Send a transactional email via SES")
    parser.add_argument("--recipient_email", required=True, help="Destination email")
    parser.add_argument(
        "--template_name",
        required=True,
        choices=sorted(VALID_TEMPLATES),
        help="Email template to use",
    )
    parser.add_argument(
        "--variables",
        required=True,
        help='JSON dict of template variables e.g. \'{"customer_name": "Jane", "order_id": "001"}\'',
    )
    args = parser.parse_args()

    try:
        variables = json.loads(args.variables)
        if not isinstance(variables, dict):
            raise ValueError("'variables' must be a JSON object")
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"'variables' is not valid JSON: {exc}"}))
        sys.exit(1)

    try:
        result = send_email(
            recipient_email=args.recipient_email,
            template_name=args.template_name,
            variables=variables,
        )
        print(json.dumps(result))
    except (ValueError, EnvironmentError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
