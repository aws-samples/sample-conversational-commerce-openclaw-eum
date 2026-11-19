"""
Shared helper for OpenClaw tools to call the Claw Boutique Store API.

All tools read these env vars:
    STORE_API_URL: Base URL of the Store API (required)
    STORE_API_TOKEN: Raw bearer token (local dev override; takes priority)
    STORE_API_TOKEN_SECRET_ARN: Secrets Manager secret ARN. The token is fetched
        from this secret on first call and cached for the life of the process.

At least one of STORE_API_TOKEN or STORE_API_TOKEN_SECRET_ARN must be set.
AWS_REGION is required when using STORE_API_TOKEN_SECRET_ARN.
"""

import json
import os
import urllib.request
import urllib.error

# Process-level cache so the secret is fetched only once per container.
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

    region = os.environ.get("AWS_REGION", "").strip()
    if not region:
        raise EnvironmentError(
            "AWS_REGION must be set to fetch the Store API token from Secrets Manager."
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


def _base_url() -> str:
    url = os.environ.get("STORE_API_URL", "").rstrip("/")
    if not url:
        raise EnvironmentError("STORE_API_URL environment variable is not set")
    return url


def _headers() -> dict:
    token = _get_token()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def api_get(path: str, params: dict | None = None) -> dict | list:
    """Make a GET request to the Store API."""
    url = f"{_base_url()}{path}"
    if params:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v is not None)
        if qs:
            url = f"{url}?{qs}"

    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        try:
            err = json.loads(body)
            raise ValueError(err.get("error", f"API error {exc.code}: {body}")) from exc
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"API error {exc.code}: {body}") from exc


def api_post(path: str, body: dict) -> dict:
    """Make a POST request to the Store API."""
    url = f"{_base_url()}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode() if exc.fp else ""
        try:
            err = json.loads(err_body)
            raise ValueError(err.get("error", f"API error {exc.code}: {err_body}")) from exc
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"API error {exc.code}: {err_body}") from exc


def api_patch(path: str, body: dict) -> dict:
    """Make a PATCH request to the Store API."""
    url = f"{_base_url()}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode() if exc.fp else ""
        try:
            err = json.loads(err_body)
            raise ValueError(err.get("error", f"API error {exc.code}: {err_body}")) from exc
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"API error {exc.code}: {err_body}") from exc
