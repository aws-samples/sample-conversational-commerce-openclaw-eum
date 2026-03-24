"""
Shared helper for OpenClaw tools to call the Claw Boutique Store API.

All tools read these env vars:
    STORE_API_URL  — Base URL of the Store API (e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod)
    STORE_API_KEY  — API key for authentication (optional, sent as x-api-key header)
"""

import json
import os
import urllib.request
import urllib.error


def _base_url() -> str:
    url = os.environ.get("STORE_API_URL", "").rstrip("/")
    if not url:
        raise EnvironmentError("STORE_API_URL environment variable is not set")
    return url


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("STORE_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


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
