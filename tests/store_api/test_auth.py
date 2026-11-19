"""
tests/store_api/test_auth.py

Auth guard tests for server.py.  No MySQL, no AWS: get_db is monkeypatched
to a fake recording DB and boto3 Secrets Manager is never called because
STORE_API_TOKEN is set directly in the test environment.
"""

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup -- server.py lives in lambda/store-api/
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SERVER_DIR = os.path.join(_REPO_ROOT, "lambda", "store-api")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# Provide minimal env vars so the DB config helpers do not raise on import.
os.environ.setdefault("DB_USER", "testuser")
os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("DB_NAME", "testdb")
# Use a known token for most tests; individual tests override as needed.
os.environ["STORE_API_TOKEN"] = "testtoken123"

import server  # noqa: E402  (must come after sys.path and env setup)

# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Context-manager cursor that records SQL calls and returns scripted rows."""

    def __init__(self, calls_list, row_factory=None):
        self._calls = calls_list
        self._row_factory = row_factory or (lambda sql, params: [])
        self._last_sql = ""
        self._last_params = None
        self.lastrowid = 1
        self.rowcount = 1

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        self._last_sql = sql
        self._last_params = params

    def fetchone(self):
        rows = self._row_factory(self._last_sql, self._last_params)
        return rows[0] if rows else None

    def fetchall(self):
        return self._row_factory(self._last_sql, self._last_params)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass


def _make_get_db(calls_list, row_factory=None):
    """Return a get_db replacement that uses the fake cursor."""
    @contextmanager
    def _fake():
        cur = _FakeCursor(calls_list, row_factory)
        yield _FakeConn(cur)
    return _fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_token_cache():
    """Reset the per-container token cache between tests."""
    server._cached_api_token = None
    server._token_configured = None
    yield
    server._cached_api_token = None
    server._token_configured = None


@pytest.fixture()
def client(monkeypatch):
    """Test client with token configured and a no-op DB."""
    os.environ["STORE_API_TOKEN"] = "testtoken123"
    calls = []
    monkeypatch.setattr(server, "get_db", _make_get_db(calls, _default_row_factory))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c, calls


@pytest.fixture()
def anon_client(monkeypatch):
    """Test client with token configured but no Authorization header (anonymous)."""
    os.environ["STORE_API_TOKEN"] = "testtoken123"
    calls = []
    monkeypatch.setattr(server, "get_db", _make_get_db(calls, _default_row_factory))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c, calls


@pytest.fixture()
def no_token_client(monkeypatch):
    """Test client with no token source configured at all."""
    saved = os.environ.pop("STORE_API_TOKEN", None)
    os.environ.pop("STORE_API_TOKEN_SECRET_ARN", None)
    calls = []
    monkeypatch.setattr(server, "get_db", _make_get_db(calls, _default_row_factory))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c, calls
    if saved is not None:
        os.environ["STORE_API_TOKEN"] = saved


VALID_TOKEN = "testtoken123"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}
BAD_AUTH = {"Authorization": "Bearer wrongtoken"}


_PRODUCT_ROW = {
    "id": 1, "name": "Widget", "description": "A widget",
    "category": "general", "size": "M", "color": "red",
    "price": 9.99, "stock_qty": 10, "created_at": None,
    # extra fields for stock/analysis queries
    "units_sold": 2, "order_count": 1,
}

_ORDER_ROW = {
    "id": 1, "status": "pending", "customer_id": 1,
    "customer_name": "Alice", "customer_phone": "+6512345678",
    "customer_email": "a@example.com", "channel": "web",
    "total": 9.99, "created_at": None, "shipped_at": None,
    "tracking_url": None,
}

_STATS_ROW = {
    "total_orders": 1, "pending_orders": 0, "total_revenue": 9.99,
    "active_escalations": 0, "total_customers": 1, "total_products": 1,
}


def _default_row_factory(sql, params):
    """Return plausible rows for common SELECT patterns."""
    s = (sql or "").lower()
    if "select" in s and "total_orders" in s:
        return [_STATS_ROW]
    if "from customers" in s:
        return [{"id": 1, "name": "Alice", "phone": "+6512345678", "email": "a@example.com"}]
    if "from products" in s:
        return [dict(_PRODUCT_ROW)]
    if "from orders" in s:
        return [dict(_ORDER_ROW)]
    if "from escalations" in s:
        return [{"id": 1, "customer_phone": "+6512345678", "reason": "r",
                 "summary": "s", "message_thread": "[]", "created_at": None,
                 "seller_notified": 0, "resolved": 0}]
    if "from admin_actions" in s:
        return []
    if "from reviews" in s:
        return [{"id": 1, "customer_phone": "+6512345678", "customer_name": "Alice",
                 "order_id": 1, "rating": 5, "review_text": "great", "created_at": None}]
    if "from interaction_memory" in s or "interaction_memory" in s:
        return []
    if "from abandoned_carts" in s:
        return []
    return []


# ---------------------------------------------------------------------------
# Helper: collect every (method, rule) pair from the url_map
# ---------------------------------------------------------------------------

def _all_routes():
    """Return list of (method, rule_string) for every registered route."""
    routes = []
    for rule in server.app.url_map.iter_rules():
        for method in rule.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            routes.append((method, rule.rule))
    return routes


_PUBLIC = {
    ("GET",  "/api/health"),
    ("GET",  "/api/products"),
    ("GET",  "/api/products/<int:product_id>"),
    ("POST", "/api/orders"),
    ("POST", "/api/carts/save"),
}


def _is_public(method, rule):
    return (method, rule) in _PUBLIC


def _make_url(rule):
    """Replace Flask variable segments with safe placeholder values."""
    url = rule
    url = url.replace("<int:product_id>", "1")
    url = url.replace("<int:order_id>", "1")
    url = url.replace("<int:escalation_id>", "1")
    url = url.replace("<int:customer_id>", "1")
    return url


# ---------------------------------------------------------------------------
# 1. Every protected route returns 401 for anonymous callers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,rule", [
    (m, r) for m, r in _all_routes() if not _is_public(m, r)
])
def test_protected_routes_require_auth(anon_client, method, rule):
    c, _ = anon_client
    url = _make_url(rule)
    resp = c.open(url, method=method, content_type="application/json", data="{}")
    assert resp.status_code == 401, (
        f"{method} {rule} should be 401 for anonymous callers, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 2. Public routes are not 401 for anonymous callers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,rule", list(_PUBLIC))
def test_public_routes_not_blocked(anon_client, method, rule):
    c, _ = anon_client
    url = _make_url(rule)
    resp = c.open(url, method=method, content_type="application/json",
                  data='{"customer_name":"A","items":[{"product_id":1,"qty":1}],"session_id":"s1"}')
    assert resp.status_code != 401, (
        f"{method} {rule} must not return 401 for anonymous callers, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 3. Valid token is never 401
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,rule", _all_routes())
def test_valid_token_never_401(client, method, rule):
    c, _ = client
    url = _make_url(rule)
    resp = c.open(url, method=method, headers=AUTH,
                  content_type="application/json",
                  data='{"customer_name":"A","items":[{"product_id":1,"qty":1}],'
                       '"session_id":"s1","interaction_type":"order","summary":"s",'
                       '"customer_phone":"+6512345678","reason":"r","new_status":"confirmed",'
                       '"resolution":"ok","action_taken":"resolved","stock_qty":5,'
                       '"action":"restock","product_name":"Widget"}')
    assert resp.status_code != 401, (
        f"{method} {rule} returned 401 for valid token"
    )


# ---------------------------------------------------------------------------
# 4. Wrong token is always 401
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,rule", _all_routes())
def test_wrong_token_is_401(anon_client, method, rule):
    c, _ = anon_client
    url = _make_url(rule)
    resp = c.open(url, method=method, headers=BAD_AUTH,
                  content_type="application/json", data="{}")
    assert resp.status_code == 401, (
        f"{method} {rule} should return 401 for wrong token, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 5. No token source: 503 on protected routes, public routes still work
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,rule", [
    (m, r) for m, r in _all_routes() if not _is_public(m, r)
])
def test_no_token_source_503_on_protected(no_token_client, method, rule):
    c, _ = no_token_client
    url = _make_url(rule)
    resp = c.open(url, method=method, content_type="application/json", data="{}")
    assert resp.status_code == 503, (
        f"{method} {rule} should be 503 with no token source, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,rule", list(_PUBLIC))
def test_no_token_source_public_routes_work(no_token_client, method, rule):
    c, _ = no_token_client
    url = _make_url(rule)
    resp = c.open(url, method=method, content_type="application/json",
                  data='{"customer_name":"A","items":[{"product_id":1,"qty":1}],"session_id":"s1"}')
    assert resp.status_code != 401
    assert resp.status_code != 503


# ---------------------------------------------------------------------------
# 6. Reporter PoC calls are 401 anonymously
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,url", [
    ("GET",   "/api/customers?name=a"),
    ("PATCH", "/api/products/1"),
    ("POST",  "/api/products/reset-stock"),
])
def test_reporter_poc_401(anon_client, method, url):
    c, _ = anon_client
    resp = c.open(url, method=method, content_type="application/json",
                  data='{"price": 0.01}')
    assert resp.status_code == 401, (
        f"{method} {url} should be 401 for anonymous callers, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 7. Anonymous POST /api/orders with existing phone must not UPDATE name/email
# ---------------------------------------------------------------------------

def test_anonymous_order_does_not_overwrite_customer(monkeypatch):
    """When an anonymous caller POSTs /api/orders and the phone already exists,
    no UPDATE customers statement should be issued."""
    os.environ["STORE_API_TOKEN"] = "testtoken123"
    server._cached_api_token = None
    server._token_configured = None

    sql_calls = []

    def _row_factory(sql, params):
        s = (sql or "").lower()
        if "from customers" in s:
            return [{"id": 99, "name": "Existing", "phone": "+6512345678",
                     "email": "existing@example.com"}]
        if "from products" in s:
            return [{"id": 1, "name": "Widget", "price": 9.99, "stock_qty": 10}]
        return []

    monkeypatch.setattr(server, "get_db", _make_get_db(sql_calls, _row_factory))
    # Silence post-order side effects
    monkeypatch.setattr(server, "_check_stock_and_alert", lambda pids: None)
    monkeypatch.setattr(server, "_send_order_confirmation_email",
                        lambda **kw: None)
    monkeypatch.setattr(server, "_send_whatsapp", lambda *a, **kw: None)

    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        resp = c.post(
            "/api/orders",
            json={
                "customer_name": "Attacker",
                "customer_email": "attacker@example.com",
                "customer_phone": "+6512345678",
                "items": [{"product_id": 1, "qty": 1}],
            },
        )

    # Request should succeed (201) or at least not 4xx due to auth
    assert resp.status_code not in (401, 403), (
        f"Anonymous POST /api/orders should not be blocked, got {resp.status_code}"
    )

    # No UPDATE customers must appear in the SQL calls
    update_calls = [
        sql for sql, _ in sql_calls
        if "update customers" in (sql or "").lower()
    ]
    assert update_calls == [], (
        f"Anonymous order must not UPDATE customers, but found: {update_calls}"
    )


# ---------------------------------------------------------------------------
# 8. Validation rejects bad inputs
# ---------------------------------------------------------------------------

@pytest.fixture()
def order_client(monkeypatch):
    os.environ["STORE_API_TOKEN"] = "testtoken123"
    server._cached_api_token = None
    server._token_configured = None
    calls = []
    monkeypatch.setattr(server, "get_db", _make_get_db(calls, _default_row_factory))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def _post_order(c, **kwargs):
    payload = {
        "customer_name": "Alice",
        "items": [{"product_id": 1, "qty": 1}],
    }
    payload.update(kwargs)
    return c.post("/api/orders", json=payload)


def test_validation_long_name(order_client):
    resp = _post_order(order_client, customer_name="A" * 101)
    assert resp.status_code == 400
    assert b"customer_name" in resp.data


def test_validation_bad_email_no_at(order_client):
    resp = _post_order(order_client, customer_email="notanemail")
    assert resp.status_code == 400
    assert b"customer_email" in resp.data


def test_validation_bad_email_no_dot(order_client):
    resp = _post_order(order_client, customer_email="user@nodotdomain")
    assert resp.status_code == 400
    assert b"customer_email" in resp.data


def test_validation_email_too_long(order_client):
    resp = _post_order(order_client, customer_email="a" * 250 + "@b.com")
    assert resp.status_code == 400
    assert b"customer_email" in resp.data


def test_validation_phone_no_plus(order_client):
    resp = _post_order(order_client, customer_phone="6512345678")
    assert resp.status_code == 400
    assert b"customer_phone" in resp.data


def test_validation_phone_too_short(order_client):
    resp = _post_order(order_client, customer_phone="+123456")
    assert resp.status_code == 400
    assert b"customer_phone" in resp.data


def test_validation_phone_too_long(order_client):
    resp = _post_order(order_client, customer_phone="+1234567890123456")
    assert resp.status_code == 400
    assert b"customer_phone" in resp.data


def test_validation_valid_phone_accepted(order_client):
    resp = _post_order(order_client, customer_phone="+6512345678")
    # Should not fail with 400 due to phone validation
    assert resp.status_code != 400 or b"customer_phone" not in resp.data


def test_validation_valid_email_accepted(order_client):
    resp = _post_order(order_client, customer_email="user@example.com")
    assert resp.status_code != 400 or b"customer_email" not in resp.data
