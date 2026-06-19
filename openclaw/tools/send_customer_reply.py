#!/usr/bin/env python3
"""
send_customer_reply.py - Send a WhatsApp message to a customer via
                          AWS End User Messaging Social (EUMS).

Called by the OpenClaw tool system (Docker sandbox). Uses boto3 to call
the social-messaging:SendWhatsAppMessage API.

Required environment variables:
    WHATSAPP_PHONE_NUMBER_ID  The EUMS origination phone number ID
                              (e.g. "phone-number-id-abcdef1234...")
    AWS_REGION                AWS region where EUMS is configured

Input  (CLI args):
    --customer_phone  <str>   Recipient in E.164 format e.g. "+639171234567" (required)
    --message_type    <str>   "text" or "template"                            (required)
    --message_content <str>   Plain text body (required when type=text)
    --template_name   <str>   Approved template name (required when type=template)
    --template_vars   <JSON>  '{"1": "value1", "2": "value2"}' for template components
                              (optional, used when type=template)

Output (stdout, JSON):
    {
        "success": bool,
        "message_id": str | null
    }
    On error: {"error": "<message>"}
"""

import argparse
import base64
import json
import os
import sys


# ---------------------------------------------------------------------------
# Payload builders (WhatsApp Cloud API JSON format, sent via EUMS)
# ---------------------------------------------------------------------------

def _build_text_payload(to: str, message_content: str) -> dict:
    """Build a WhatsApp text message payload."""
    try:
        body = base64.b64decode(message_content.encode()).decode("utf-8")
    except Exception:
        body = message_content

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": body,
        },
    }


def _build_template_payload(
    to: str,
    template_name: str,
    template_vars: dict | None,
) -> dict:
    """Build a WhatsApp template message payload."""
    components = []

    if template_vars:
        sorted_keys = sorted(template_vars.keys(), key=lambda k: int(k) if k.isdigit() else 0)
        parameters = [
            {"type": "text", "text": str(template_vars[k])} for k in sorted_keys
        ]
        components.append({"type": "body", "parameters": parameters})

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components,
        },
    }


# ---------------------------------------------------------------------------
# AWS EUMS send helper
# ---------------------------------------------------------------------------

def _send_via_eums(payload: dict) -> dict:
    """
    Send a WhatsApp message via AWS End User Messaging Social.

    Uses boto3 social-messaging client's send_whatsapp_message API.
    The message payload is the standard WhatsApp Cloud API JSON format.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        raise RuntimeError(
            "boto3 is required for AWS EUMS. Install with: pip install boto3"
        )

    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not phone_number_id:
        raise EnvironmentError("Missing required env var: WHATSAPP_PHONE_NUMBER_ID")

    region = os.environ.get("AWS_REGION", "us-east-1")

    client = boto3.client("socialmessaging", region_name=region)

    message_bytes = json.dumps(payload).encode("utf-8")

    try:
        response = client.send_whatsapp_message(
            originationPhoneNumberId=phone_number_id,
            message=message_bytes,
            metaApiVersion="v21.0",
        )
        return {
            "messageId": response.get("messageId"),
        }
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"EUMS SendWhatsAppMessage failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def send_customer_reply(
    customer_phone: str,
    message_type: str,
    message_content: str | None = None,
    template_name: str | None = None,
    template_vars: dict | None = None,
) -> dict:
    """
    Send a WhatsApp message to the customer via AWS EUMS.

    Args:
        customer_phone: Recipient in E.164 format.
        message_type:   "text" or "template".
        message_content: Body text (required for message_type="text").
        template_name:  Approved template name (required for message_type="template").
        template_vars:  Optional dict of positional template parameters.

    Returns:
        dict with 'success' (bool) and 'message_id' (str | None).
    """
    message_type = message_type.strip().lower()
    if message_type not in ("text", "template"):
        raise ValueError("message_type must be 'text' or 'template'")

    if message_type == "text":
        if not message_content:
            raise ValueError("message_content is required when message_type is 'text'")
        payload = _build_text_payload(customer_phone, message_content)
    else:
        if not template_name:
            raise ValueError("template_name is required when message_type is 'template'")
        payload = _build_template_payload(customer_phone, template_name, template_vars)

    response = _send_via_eums(payload)

    return {
        "success": True,
        "message_id": response.get("messageId"),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Send a WhatsApp message to a customer via AWS EUMS"
    )
    parser.add_argument(
        "--customer_phone", required=True, help="Recipient E.164 phone number"
    )
    parser.add_argument(
        "--message_type",
        required=True,
        choices=["text", "template"],
        help="Message type: 'text' for free-form, 'template' for pre-approved template",
    )
    parser.add_argument(
        "--message_content",
        default=None,
        help="Message body text (required for type=text).",
    )
    parser.add_argument(
        "--template_name",
        default=None,
        help="Approved WhatsApp template name (required for type=template)",
    )
    parser.add_argument(
        "--template_vars",
        default=None,
        help='JSON dict of positional template vars e.g. \'{"1": "Jane", "2": "ORD-001"}\'',
    )
    args = parser.parse_args()

    template_vars: dict | None = None
    if args.template_vars:
        try:
            template_vars = json.loads(args.template_vars)
            if not isinstance(template_vars, dict):
                raise ValueError("template_vars must be a JSON object")
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"template_vars is not valid JSON: {exc}"}))
            sys.exit(1)

    try:
        result = send_customer_reply(
            customer_phone=args.customer_phone,
            message_type=args.message_type,
            message_content=args.message_content,
            template_name=args.template_name,
            template_vars=template_vars,
        )
        print(json.dumps(result))
    except (ValueError, EnvironmentError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
