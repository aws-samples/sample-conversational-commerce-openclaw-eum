#!/usr/bin/env python3
"""
send_customer_reply.py - Send a WhatsApp message to a customer via the
                          WhatsApp Business API (Cloud API).

Called by the OpenClaw tool system (Docker sandbox). Reads API credentials
from environment variables and returns a single JSON object to stdout.

Required environment variables:
    WHATSAPP_API_URL        Base URL, e.g. "https://graph.facebook.com/v19.0"
    WHATSAPP_PHONE_NUMBER_ID  The sender phone-number ID from Meta Business Manager
    WHATSAPP_TOKEN          Permanent system-user access token

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

Notes on the WhatsApp Cloud API request body:
    - Text messages use the "text" object with body base64-encoded to stay safe
      inside the Docker sandbox JSON transport layer.
    - Template messages reference a pre-approved template by name and pass
      component parameters as positional body components.
    - The outgoing HTTP payload itself is standard JSON (not base64); the
      base64 encoding is applied to the user-supplied message_content so that
      special characters and newlines don't break the tool→OpenClaw boundary.
"""

import argparse
import base64
import json
import os
import sys

import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def get_whatsapp_config() -> dict:
    """Read WhatsApp API credentials from environment variables."""
    required = ("WHATSAPP_API_URL", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TOKEN")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )
    return {
        "api_url": os.environ["WHATSAPP_API_URL"].rstrip("/"),
        "phone_number_id": os.environ["WHATSAPP_PHONE_NUMBER_ID"],
        "token": os.environ["WHATSAPP_TOKEN"],
    }


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _build_text_payload(to: str, message_content: str) -> dict:
    """
    Build a WhatsApp Cloud API text message payload.

    The message_content is base64-decoded from the CLI argument so that
    the OpenClaw tool layer can pass multi-line / special-char content
    safely as a base64 string. If the input is not valid base64, it is
    used as-is (plain text fallback for direct local testing).
    """
    # Attempt base64 decode; fall back to raw string
    try:
        body = base64.b64decode(message_content.encode()).decode("utf-8")
    except Exception:  # noqa: BLE001
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
    """
    Build a WhatsApp Cloud API template message payload.

    Args:
        to:            Recipient phone in E.164 format.
        template_name: Exact name of the approved Meta template.
        template_vars: Optional dict mapping positional keys ("1", "2", …)
                       to parameter values injected into the template body
                       component.
    """
    components = []

    if template_vars:
        # Convert {"1": "foo", "2": "bar"} into ordered body parameters
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
# HTTP helper
# ---------------------------------------------------------------------------

def _post_to_whatsapp(config: dict, payload: dict) -> dict:
    """
    POST the message payload to the WhatsApp Cloud API.

    Uses stdlib urllib to avoid requiring the 'requests' library inside the
    Docker sandbox (only standard library + pymysql are assumed available).

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: On HTTP error or JSON parse failure.
    """
    url = f"{config['api_url']}/{config['phone_number_id']}/messages"
    body_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=body_bytes,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['token']}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(
            f"WhatsApp API HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"WhatsApp API network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"WhatsApp API returned invalid JSON: {exc}") from exc


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
    Send a WhatsApp message to the customer.

    Args:
        customer_phone: Recipient in E.164 format.
        message_type:   "text" or "template".
        message_content: Body text (required for message_type="text").
                         Should be base64-encoded when coming from the
                         OpenClaw tool boundary.
        template_name:  Approved template name (required for message_type="template").
        template_vars:  Optional dict of positional template parameters.

    Returns:
        dict with 'success' (bool) and 'message_id' (str | None).
    """
    # Input validation
    message_type = message_type.strip().lower()
    if message_type not in ("text", "template"):
        raise ValueError("message_type must be 'text' or 'template'")

    if message_type == "text":
        if not message_content:
            raise ValueError("message_content is required when message_type is 'text'")
        payload = _build_text_payload(customer_phone, message_content)

    else:  # template
        if not template_name:
            raise ValueError("template_name is required when message_type is 'template'")
        payload = _build_template_payload(customer_phone, template_name, template_vars)

    config = get_whatsapp_config()
    response = _post_to_whatsapp(config, payload)

    # Extract message ID from Cloud API response shape:
    # {"messages": [{"id": "wamid.xxx"}]}
    message_id = None
    messages = response.get("messages", [])
    if messages and isinstance(messages, list):
        message_id = messages[0].get("id")

    return {
        "success": True,
        "message_id": message_id,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Send a WhatsApp message to a customer"
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
        help=(
            "Message body text (required for type=text). "
            "Pass as base64-encoded string when invoking from OpenClaw tool boundary."
        ),
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

    # Parse optional template_vars JSON
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
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
