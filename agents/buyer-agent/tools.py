"""Store API tools for the buyer-facing WhatsApp agent."""

import json
import os
import urllib.parse
import urllib.request
from strands import tool

STORE_API_URL = os.environ.get("STORE_API_URL", "").rstrip("/")

# Process-level token cache; fetched from Secrets Manager at most once.
_cached_token: str | None = None


def _get_token() -> str:
    """Return the bearer token, fetching from Secrets Manager if needed."""
    global _cached_token
    if _cached_token is not None:
        return _cached_token

    raw = os.environ.get("STORE_API_TOKEN", "").strip()
    if raw:
        _cached_token = raw
        return _cached_token

    secret_arn = os.environ.get("STORE_API_TOKEN_SECRET_ARN", "").strip()
    if not secret_arn:
        raise EnvironmentError(
            "Store API authentication is not configured. "
            "Set STORE_API_TOKEN or STORE_API_TOKEN_SECRET_ARN."
        )

    region = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "").strip()
    if not region:
        raise EnvironmentError(
            "AWS_REGION or AWS_DEFAULT_REGION must be set to fetch the Store API token from Secrets Manager."
        )

    import boto3
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_arn)
    token = response["SecretString"].strip()
    if not token:
        raise EnvironmentError(
            f"Secrets Manager secret {secret_arn} returned an empty value."
        )
    _cached_token = token
    return _cached_token


def _auth_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_token()}",
    }


def _http_get(path: str, query_params: dict | None = None) -> dict:
    url = STORE_API_URL + path
    if query_params:
        filtered = {k: v for k, v in query_params.items() if v is not None}
        if filtered:
            url += "?" + urllib.parse.urlencode(filtered)
    req = urllib.request.Request(url, method="GET")
    for k, v in _auth_headers().items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _http_post(path: str, body: dict) -> dict:
    url = STORE_API_URL + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in _auth_headers().items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


@tool
def list_products(category: str = None, size: str = None, color: str = None) -> str:
    """Search the product catalog. Returns matching products with name, price, stock, sizes, and colors.

    Args:
        category: Product category filter (e.g., tops, dresses, accessories)
        size: Size filter (e.g., XS, S, M, L, XL)
        color: Color filter
    """
    result = _http_get("/api/products", {
        "category": category,
        "size": size,
        "color": color,
    })
    return json.dumps(result)


@tool
def get_product(product_id: int) -> str:
    """Get full details for a single product by its ID, including price, stock level, available sizes, and colors.

    Args:
        product_id: Numeric product ID
    """
    result = _http_get(f"/api/products/{urllib.parse.quote(str(product_id))}")
    return json.dumps(result)


@tool
def get_order(order_id: int) -> str:
    """Look up an order by order ID. Returns order status, items, and total.

    Args:
        order_id: Numeric order ID
    """
    result = _http_get(f"/api/orders/{urllib.parse.quote(str(order_id))}")
    return json.dumps(result)


@tool
def create_escalation(customer_phone: str, reason: str, summary: str, order_id: int = None) -> str:
    """Log a customer issue or complaint so the store owner is notified. Use this when a customer has a problem that needs human follow-up.

    Args:
        customer_phone: Customer WhatsApp phone number in E.164 format
        reason: Short description of the issue or complaint
        summary: Brief summary of the conversation context
        order_id: Order ID related to the issue, if applicable
    """
    body = {
        "customer_phone": customer_phone,
        "reason": reason,
        "summary": summary,
    }
    if order_id is not None:
        body["order_id"] = order_id
    result = _http_post("/api/escalations", body)
    return json.dumps(result)
