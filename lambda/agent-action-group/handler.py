"""
Bedrock Agent action group handler.

Receives action group invocations from a Bedrock Agent and proxies them
to the Store API. Uses only stdlib — no external dependencies required.

Environment variables:
  STORE_API_URL  Base URL of the Store API, e.g.
                 https://h08zylpngj.execute-api.us-east-1.amazonaws.com/prod
"""
import json
import os
import urllib.parse
import urllib.request


STORE_API_URL = os.environ.get("STORE_API_URL", "").rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params_to_dict(parameters):
    """Convert Bedrock's parameter list to a plain dict."""
    if not parameters:
        return {}
    return {p["name"]: p["value"] for p in parameters}


def _http_get(path, query_params=None):
    url = STORE_API_URL + path
    if query_params:
        filtered = {k: v for k, v in query_params.items() if v is not None}
        if filtered:
            url += "?" + urllib.parse.urlencode(filtered)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _http_post(path, body):
    url = STORE_API_URL + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Function implementations
# ---------------------------------------------------------------------------

def list_products(params):
    return _http_get("/api/products", {
        "category": params.get("category"),
        "size":     params.get("size"),
        "color":    params.get("color"),
    })


def get_product(params):
    product_id = params["product_id"]
    return _http_get(f"/api/products/{urllib.parse.quote(str(product_id))}")


def get_order(params):
    order_id = params["order_id"]
    return _http_get(f"/api/orders/{urllib.parse.quote(str(order_id))}")


def create_escalation(params):
    body = {
        "order_id":       params.get("order_id"),
        "reason":         params.get("reason"),
        "customer_phone": params.get("customer_phone"),
    }
    return _http_post("/api/escalations", body)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

FUNCTION_MAP = {
    "list_products":     list_products,
    "get_product":       get_product,
    "get_order":         get_order,
    "create_escalation": create_escalation,
}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    action_group = event.get("actionGroup", "StoreActions")
    function_name = event.get("function", "")
    parameters = event.get("parameters", [])

    params = _params_to_dict(parameters)

    func = FUNCTION_MAP.get(function_name)
    if func is None:
        result = {"error": f"Unknown function: {function_name}"}
    else:
        try:
            result = func(params)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            try:
                result = {"error": json.loads(body)}
            except (json.JSONDecodeError, ValueError):
                result = {"error": body or str(exc)}
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps(result)}
                }
            },
        },
    }
