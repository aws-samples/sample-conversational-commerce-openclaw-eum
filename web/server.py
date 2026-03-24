#!/usr/bin/env python3
"""
server.py - Flask REST API for the Claw Boutique e-commerce platform.

Reads DB credentials from environment variables:
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

Serves static files from web/static/ and exposes REST endpoints for
products, orders, escalations, stats, and interaction memory.
"""

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Resolve static folder relative to this file so the server works regardless
# of the working directory it is launched from.
_HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_HERE, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
CORS(app)  # Allow cross-origin requests during development

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _db_config() -> dict:
    """Build mysql.connector kwargs from environment variables."""
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", 3306)),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "autocommit": False,
        "connect_timeout": 10,
        "use_unicode": True,
        "charset": "utf8mb4",
    }


@contextmanager
def get_db():
    """Yield a mysql.connector connection, committing on success and rolling
    back on any exception. Always closes the connection on exit."""
    conn = mysql.connector.connect(**_db_config())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cursor(conn, dictionary: bool = True):
    """Return a cursor; dictionary=True returns rows as dicts."""
    return conn.cursor(dictionary=dictionary)


# ---------------------------------------------------------------------------
# Startup: ensure new tables exist
# ---------------------------------------------------------------------------

def _ensure_tables() -> None:
    """Create tables required by this server if they do not already exist."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS admin_actions (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            escalation_id INT UNSIGNED,
            action_type VARCHAR(50) NOT NULL,
            resolution TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_admin_actions_escalation (escalation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS interaction_memory (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            customer_phone VARCHAR(20),
            interaction_type VARCHAR(50) NOT NULL,
            summary TEXT NOT NULL,
            resolution TEXT,
            tags JSON,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_memory_phone (customer_phone),
            KEY idx_memory_type (interaction_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            customer_phone VARCHAR(20) NOT NULL,
            customer_name VARCHAR(120) NOT NULL,
            order_id INT UNSIGNED DEFAULT NULL,
            rating TINYINT UNSIGNED NOT NULL,
            review_text TEXT NOT NULL,
            response_sent TINYINT(1) NOT NULL DEFAULT 0,
            escalated TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_reviews_rating (rating)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS abandoned_carts (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            session_id VARCHAR(64) NOT NULL,
            customer_phone VARCHAR(20) DEFAULT NULL,
            customer_email VARCHAR(254) DEFAULT NULL,
            customer_name VARCHAR(120) DEFAULT NULL,
            cart_json JSON NOT NULL,
            recovered TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_abandoned_carts_session (session_id)
        )
        """,
    ]
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                for stmt in ddl_statements:
                    cur.execute(stmt)
        logger.info("Table check/create completed.")
    except Exception as exc:
        logger.error("Failed to ensure tables: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _err(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _not_found(resource: str = "Resource"):
    return _err(f"{resource} not found.", 404)


# ---------------------------------------------------------------------------
# Static file serving (index.html fallback for SPA)
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    """Serve files from static/; fall back to index.html for SPA routing."""
    full_path = os.path.join(STATIC_DIR, path)
    if os.path.isfile(full_path):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def list_products():
    """
    GET /api/products
    Query params: category, size, color (all optional)
    """
    category = request.args.get("category", "").strip() or None
    size = request.args.get("size", "").strip() or None
    color = request.args.get("color", "").strip() or None

    conditions = []
    params = []

    if category:
        conditions.append("LOWER(category) = LOWER(%s)")
        params.append(category)
    if size:
        conditions.append("LOWER(size) = LOWER(%s)")
        params.append(size)
    if color:
        conditions.append("LOWER(color) = LOWER(%s)")
        params.append(color)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT id, name, description, category, size, color,
               price, stock_qty, created_at
        FROM products
        {where}
        ORDER BY category, name
    """

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_products error")
        return _err(str(exc), 500)

    products = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "category": r["category"],
            "size": r["size"],
            "color": r["color"],
            "price": float(r["price"]),
            "stock_qty": int(r["stock_qty"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return jsonify(products)


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id: int):
    """
    GET /api/products/<id>
    Returns a single product.
    """
    sql = """
        SELECT id, name, description, category, size, color,
               price, stock_qty, created_at
        FROM products
        WHERE id = %s
    """
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql, (product_id,))
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("get_product error")
        return _err(str(exc), 500)

    if not row:
        return _not_found("Product")

    return jsonify(
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "size": row["size"],
            "color": row["color"],
            "price": float(row["price"]),
            "stock_qty": int(row["stock_qty"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

# Valid state-machine transitions
_ORDER_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["shipped", "cancelled"],
    "processing": ["shipped", "cancelled"],
    "shipped": ["delivered"],
    "delivered": [],
    "cancelled": [],
    "refunded": [],
}


@app.route("/api/orders", methods=["POST"])
def create_order():
    """
    POST /api/orders
    Body: {customer_name, customer_email, customer_phone, items: [{product_id, qty}]}
    Returns: {order_id, total}
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    customer_name = (body.get("customer_name") or "").strip()
    customer_email = (body.get("customer_email") or "").strip() or None
    customer_phone = (body.get("customer_phone") or "").strip() or None
    items = body.get("items")

    if not customer_name:
        return _err("customer_name is required.")
    if not items or not isinstance(items, list) or len(items) == 0:
        return _err("items must be a non-empty list.")

    for idx, item in enumerate(items):
        if not isinstance(item.get("product_id"), int) or item["product_id"] < 1:
            return _err(f"items[{idx}].product_id must be a positive integer.")
        if not isinstance(item.get("qty"), int) or item["qty"] < 1:
            return _err(f"items[{idx}].qty must be a positive integer.")

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                # -- Upsert customer --
                if customer_phone:
                    cur.execute(
                        "SELECT id FROM customers WHERE phone = %s LIMIT 1",
                        (customer_phone,),
                    )
                    existing = cur.fetchone()
                else:
                    existing = None

                if existing:
                    customer_id = existing["id"]
                    # Update name/email if provided
                    cur.execute(
                        "UPDATE customers SET name = %s, email = COALESCE(%s, email) WHERE id = %s",
                        (customer_name, customer_email, customer_id),
                    )
                else:
                    cur.execute(
                        "INSERT INTO customers (name, email, phone, created_at) VALUES (%s, %s, %s, %s)",
                        (customer_name, customer_email, customer_phone, datetime.utcnow()),
                    )
                    customer_id = cur.lastrowid

                # -- Lock product rows and verify stock --
                product_ids = [item["product_id"] for item in items]
                fmt = ",".join(["%s"] * len(product_ids))
                cur.execute(
                    f"SELECT id, price, stock_qty FROM products WHERE id IN ({fmt}) FOR UPDATE",
                    product_ids,
                )
                product_rows = {r["id"]: r for r in cur.fetchall()}

                missing = [pid for pid in product_ids if pid not in product_rows]
                if missing:
                    raise ValueError(f"Product(s) not found: {missing}")

                # Aggregate qty per product_id in case duplicates appear in items list
                qty_map: dict[int, int] = {}
                for item in items:
                    qty_map[item["product_id"]] = qty_map.get(item["product_id"], 0) + item["qty"]

                insufficient = [
                    pid
                    for pid, qty in qty_map.items()
                    if product_rows[pid]["stock_qty"] < qty
                ]
                if insufficient:
                    raise ValueError(
                        f"Insufficient stock for product(s): {insufficient}"
                    )

                # -- Create order --
                total = sum(
                    float(product_rows[pid]["price"]) * qty
                    for pid, qty in qty_map.items()
                )
                cur.execute(
                    """
                    INSERT INTO orders
                        (customer_id, status, channel, total, created_at)
                    VALUES (%s, 'pending', 'web', %s, %s)
                    """,
                    (customer_id, total, datetime.utcnow()),
                )
                order_id = cur.lastrowid

                # -- Insert order_items and deduct stock --
                for pid, qty in qty_map.items():
                    unit_price = float(product_rows[pid]["price"])
                    cur.execute(
                        """
                        INSERT INTO order_items
                            (order_id, product_id, qty, unit_price)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (order_id, pid, qty, unit_price),
                    )
                    cur.execute(
                        "UPDATE products SET stock_qty = stock_qty - %s WHERE id = %s",
                        (qty, pid),
                    )

    except ValueError as exc:
        return _err(str(exc), 422)
    except Exception as exc:
        logger.exception("create_order error")
        return _err(str(exc), 500)

    return jsonify({"order_id": order_id, "total": round(total, 2)}), 201


@app.route("/api/orders", methods=["GET"])
def list_orders():
    """
    GET /api/orders  (admin)
    Query params: status, customer_id (optional)
    """
    status = request.args.get("status", "").strip() or None
    customer_id = request.args.get("customer_id", "").strip() or None

    conditions = []
    params = []

    if status:
        conditions.append("o.status = %s")
        params.append(status)
    if customer_id:
        conditions.append("o.customer_id = %s")
        params.append(int(customer_id))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT
            o.id, o.status, o.channel, o.total, o.created_at,
            o.shipped_at, o.tracking_url,
            c.id AS customer_id, c.name AS customer_name,
            c.phone AS customer_phone, c.email AS customer_email
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        {where}
        ORDER BY o.created_at DESC
        LIMIT 500
    """

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_orders error")
        return _err(str(exc), 500)

    orders = [
        {
            "id": r["id"],
            "status": r["status"],
            "channel": r["channel"],
            "total": float(r["total"]) if r["total"] is not None else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "shipped_at": r["shipped_at"].isoformat() if r["shipped_at"] else None,
            "tracking_url": r["tracking_url"],
            "customer": {
                "id": r["customer_id"],
                "name": r["customer_name"],
                "phone": r["customer_phone"],
                "email": r["customer_email"],
            },
        }
        for r in rows
    ]
    return jsonify(orders)


@app.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    """
    GET /api/orders/<id>
    Returns order detail with items and customer info.
    """
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT
                        o.id, o.status, o.channel, o.total, o.created_at,
                        o.shipped_at, o.tracking_url,
                        c.id AS customer_id, c.name AS customer_name,
                        c.phone AS customer_phone, c.email AS customer_email
                    FROM orders o
                    JOIN customers c ON c.id = o.customer_id
                    WHERE o.id = %s
                    LIMIT 1
                    """,
                    (order_id,),
                )
                order_row = cur.fetchone()

                if not order_row:
                    return _not_found("Order")

                cur.execute(
                    """
                    SELECT oi.id, oi.product_id, p.name AS product_name,
                           oi.qty, oi.unit_price
                    FROM order_items oi
                    JOIN products p ON p.id = oi.product_id
                    WHERE oi.order_id = %s
                    """,
                    (order_id,),
                )
                items = cur.fetchall()
    except Exception as exc:
        logger.exception("get_order error")
        return _err(str(exc), 500)

    return jsonify(
        {
            "id": order_row["id"],
            "status": order_row["status"],
            "channel": order_row["channel"],
            "total": float(order_row["total"]) if order_row["total"] is not None else None,
            "created_at": order_row["created_at"].isoformat() if order_row["created_at"] else None,
            "shipped_at": order_row["shipped_at"].isoformat() if order_row["shipped_at"] else None,
            "tracking_url": order_row["tracking_url"],
            "customer": {
                "id": order_row["customer_id"],
                "name": order_row["customer_name"],
                "phone": order_row["customer_phone"],
                "email": order_row["customer_email"],
            },
            "items": [
                {
                    "id": item["id"],
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "qty": item["qty"],
                    "unit_price": float(item["unit_price"]),
                }
                for item in items
            ],
        }
    )


@app.route("/api/orders/<int:order_id>/status", methods=["PATCH"])
def update_order_status(order_id: int):
    """
    PATCH /api/orders/<id>/status
    Body: {new_status, tracking_url?}
    Enforces the state machine.
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    new_status = (body.get("new_status") or "").strip()
    tracking_url = body.get("tracking_url")

    if not new_status:
        return _err("new_status is required.")

    if new_status not in _ORDER_TRANSITIONS:
        return _err(
            f"Invalid status '{new_status}'. "
            f"Allowed: {list(_ORDER_TRANSITIONS.keys())}"
        )

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    "SELECT status FROM orders WHERE id = %s LIMIT 1",
                    (order_id,),
                )
                row = cur.fetchone()
                if not row:
                    return _not_found("Order")

                current_status = row["status"]
                allowed = _ORDER_TRANSITIONS.get(current_status, [])
                if new_status not in allowed:
                    return _err(
                        f"Cannot transition from '{current_status}' to '{new_status}'. "
                        f"Allowed next states: {allowed}",
                        422,
                    )

                # Build UPDATE dynamically
                updates = ["status = %s"]
                params: list = [new_status]

                if new_status == "shipped":
                    updates.append("shipped_at = %s")
                    params.append(datetime.utcnow())

                if tracking_url is not None:
                    updates.append("tracking_url = %s")
                    params.append(tracking_url)

                params.append(order_id)
                cur.execute(
                    f"UPDATE orders SET {', '.join(updates)} WHERE id = %s",
                    params,
                )
    except Exception as exc:
        logger.exception("update_order_status error")
        return _err(str(exc), 500)

    return jsonify(
        {"order_id": order_id, "status": new_status, "tracking_url": tracking_url}
    )


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

@app.route("/api/escalations", methods=["GET"])
def list_escalations():
    """
    GET /api/escalations
    Query param: resolved (boolean string "true"/"false")
    """
    resolved_param = request.args.get("resolved", "").strip().lower()

    conditions = []
    params = []

    # The escalations table has seller_notified; we treat a non-null
    # admin_actions entry as "resolved" by joining. We use a subquery approach:
    # resolved = has at least one admin_actions row.
    if resolved_param == "true":
        conditions.append(
            "EXISTS (SELECT 1 FROM admin_actions aa WHERE aa.escalation_id = e.id)"
        )
    elif resolved_param == "false":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM admin_actions aa WHERE aa.escalation_id = e.id)"
        )

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT
            e.id, e.customer_phone, e.reason, e.summary,
            e.message_thread, e.created_at, e.seller_notified,
            EXISTS (
                SELECT 1 FROM admin_actions aa WHERE aa.escalation_id = e.id
            ) AS resolved
        FROM escalations e
        {where}
        ORDER BY e.created_at DESC
        LIMIT 500
    """

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_escalations error")
        return _err(str(exc), 500)

    escalations = [
        {
            "id": r["id"],
            "customer_phone": r["customer_phone"],
            "reason": r["reason"],
            "summary": r["summary"],
            "message_thread": (
                r["message_thread"]
                if isinstance(r["message_thread"], (dict, list))
                else (
                    json.loads(r["message_thread"])
                    if r["message_thread"]
                    else None
                )
            ),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "seller_notified": bool(r["seller_notified"]),
            "resolved": bool(r["resolved"]),
        }
        for r in rows
    ]
    return jsonify(escalations)


@app.route("/api/escalations", methods=["POST"])
def create_escalation():
    """
    POST /api/escalations
    Body: {customer_phone, reason, summary, message_thread?, seller_notified?}
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    customer_phone = (body.get("customer_phone") or "").strip()
    reason = (body.get("reason") or "").strip()
    summary = (body.get("summary") or "").strip()
    message_thread = body.get("message_thread") or []
    seller_notified = bool(body.get("seller_notified", False))

    if not customer_phone:
        return _err("customer_phone is required.")
    if not reason:
        return _err("reason is required.")
    if not summary:
        return _err("summary is required.")

    thread_json = json.dumps(message_thread) if isinstance(message_thread, (list, dict)) else message_thread

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO escalations
                        (customer_phone, reason, summary, message_thread, seller_notified, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (customer_phone, reason, summary, thread_json,
                     1 if seller_notified else 0, datetime.utcnow()),
                )
                escalation_id = cur.lastrowid
    except Exception as exc:
        logger.exception("create_escalation error")
        return _err(str(exc), 500)

    return jsonify({
        "escalation_id": escalation_id,
        "customer_phone": customer_phone,
        "reason": reason,
        "seller_notified": seller_notified,
    }), 201


@app.route("/api/escalations/<int:escalation_id>", methods=["GET"])
def get_escalation(escalation_id: int):
    """
    GET /api/escalations/<id>
    Returns single escalation with any admin actions.
    """
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT
                        e.id, e.customer_phone, e.reason, e.summary,
                        e.message_thread, e.created_at, e.seller_notified,
                        EXISTS (
                            SELECT 1 FROM admin_actions aa WHERE aa.escalation_id = e.id
                        ) AS resolved
                    FROM escalations e
                    WHERE e.id = %s
                    LIMIT 1
                    """,
                    (escalation_id,),
                )
                row = cur.fetchone()
                if not row:
                    return _not_found("Escalation")

                cur.execute(
                    """
                    SELECT id, action_type, resolution, created_at
                    FROM admin_actions
                    WHERE escalation_id = %s
                    ORDER BY created_at ASC
                    """,
                    (escalation_id,),
                )
                actions = cur.fetchall()
    except Exception as exc:
        logger.exception("get_escalation error")
        return _err(str(exc), 500)

    return jsonify(
        {
            "id": row["id"],
            "customer_phone": row["customer_phone"],
            "reason": row["reason"],
            "summary": row["summary"],
            "message_thread": (
                row["message_thread"]
                if isinstance(row["message_thread"], (dict, list))
                else (
                    json.loads(row["message_thread"])
                    if row["message_thread"]
                    else None
                )
            ),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "seller_notified": bool(row["seller_notified"]),
            "resolved": bool(row["resolved"]),
            "admin_actions": [
                {
                    "id": a["id"],
                    "action_type": a["action_type"],
                    "resolution": a["resolution"],
                    "created_at": a["created_at"].isoformat() if a["created_at"] else None,
                }
                for a in actions
            ],
        }
    )


@app.route("/api/escalations/<int:escalation_id>/resolve", methods=["POST"])
def resolve_escalation(escalation_id: int):
    """
    POST /api/escalations/<id>/resolve
    Body: {resolution, action_taken}
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    resolution = (body.get("resolution") or "").strip()
    action_taken = (body.get("action_taken") or "").strip()

    if not resolution:
        return _err("resolution is required.")
    if not action_taken:
        return _err("action_taken is required.")

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    "SELECT id FROM escalations WHERE id = %s LIMIT 1",
                    (escalation_id,),
                )
                if not cur.fetchone():
                    return _not_found("Escalation")

                cur.execute(
                    """
                    INSERT INTO admin_actions
                        (escalation_id, action_type, resolution, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (escalation_id, action_taken, resolution, datetime.utcnow()),
                )
                action_id = cur.lastrowid
    except Exception as exc:
        logger.exception("resolve_escalation error")
        return _err(str(exc), 500)

    return jsonify(
        {
            "escalation_id": escalation_id,
            "action_id": action_id,
            "action_taken": action_taken,
            "resolution": resolution,
        }
    ), 201


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats", methods=["GET"])
def get_stats():
    """
    GET /api/stats
    Returns aggregate statistics for the dashboard.
    """
    sql = """
        SELECT
            (SELECT COUNT(*) FROM orders) AS total_orders,
            (SELECT COUNT(*) FROM orders WHERE status = 'pending') AS pending_orders,
            (SELECT COALESCE(SUM(total), 0) FROM orders
             WHERE status NOT IN ('cancelled', 'refunded')) AS total_revenue,
            (SELECT COUNT(*) FROM escalations e
             WHERE NOT EXISTS (
                 SELECT 1 FROM admin_actions aa WHERE aa.escalation_id = e.id
             )) AS active_escalations,
            (SELECT COUNT(*) FROM customers) AS total_customers,
            (SELECT COUNT(*) FROM products) AS total_products
    """

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql)
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("get_stats error")
        return _err(str(exc), 500)

    return jsonify(
        {
            "total_orders": int(row["total_orders"]),
            "pending_orders": int(row["pending_orders"]),
            "total_revenue": float(row["total_revenue"]),
            "active_escalations": int(row["active_escalations"]),
            "total_customers": int(row["total_customers"]),
            "total_products": int(row["total_products"]),
        }
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@app.route("/api/memory", methods=["POST"])
def save_memory():
    """
    POST /api/memory
    Body: {customer_phone, interaction_type, summary, resolution?, tags?[]}
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    customer_phone = (body.get("customer_phone") or "").strip() or None
    interaction_type = (body.get("interaction_type") or "").strip()
    summary = (body.get("summary") or "").strip()
    resolution = (body.get("resolution") or "").strip() or None
    tags = body.get("tags")

    if not interaction_type:
        return _err("interaction_type is required.")
    if not summary:
        return _err("summary is required.")
    if tags is not None and not isinstance(tags, list):
        return _err("tags must be a list of strings.")

    tags_json = json.dumps(tags) if tags is not None else None

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO interaction_memory
                        (customer_phone, interaction_type, summary, resolution, tags, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        customer_phone,
                        interaction_type,
                        summary,
                        resolution,
                        tags_json,
                        datetime.utcnow(),
                    ),
                )
                memory_id = cur.lastrowid
    except Exception as exc:
        logger.exception("save_memory error")
        return _err(str(exc), 500)

    return jsonify({"id": memory_id, "created": True}), 201


@app.route("/api/memory", methods=["GET"])
def list_memory():
    """
    GET /api/memory
    Returns the 100 most recent interaction memories.
    Query params: customer_phone, interaction_type (optional filters)
    """
    customer_phone = request.args.get("customer_phone", "").strip() or None
    interaction_type = request.args.get("interaction_type", "").strip() or None

    conditions = []
    params = []

    if customer_phone:
        conditions.append("customer_phone = %s")
        params.append(customer_phone)
    if interaction_type:
        conditions.append("interaction_type = %s")
        params.append(interaction_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT id, customer_phone, interaction_type, summary, resolution, tags, created_at
        FROM interaction_memory
        {where}
        ORDER BY created_at DESC
        LIMIT 100
    """

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_memory error")
        return _err(str(exc), 500)

    memories = [
        {
            "id": r["id"],
            "customer_phone": r["customer_phone"],
            "interaction_type": r["interaction_type"],
            "summary": r["summary"],
            "resolution": r["resolution"],
            "tags": (
                r["tags"]
                if isinstance(r["tags"], list)
                else (json.loads(r["tags"]) if r["tags"] else None)
            ),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return jsonify(memories)


# ===========================================================================
# Reviews
# ===========================================================================

@app.route("/api/reviews", methods=["POST"])
def create_review():
    """POST /api/reviews — Submit a customer review."""
    data = request.get_json(silent=True) or {}
    required = ("customer_phone", "customer_name", "rating", "review_text")
    for field in required:
        if field not in data:
            return _err(f"Missing required field: {field}")

    rating = int(data["rating"])
    if rating < 1 or rating > 5:
        return _err("Rating must be between 1 and 5")

    conn = get_db()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """INSERT INTO reviews
                   (customer_phone, customer_name, order_id, rating, review_text)
                   VALUES (%s, %s, %s, %s, %s)""",
                (data["customer_phone"], data["customer_name"],
                 data.get("order_id"), rating, data["review_text"]),
            )
            review_id = cur.lastrowid
        conn.commit()

        # Determine action
        if rating >= 4:
            action = "auto_thank"
        elif rating == 3:
            action = "follow_up"
        else:
            action = "escalate"

        return jsonify({
            "review_id": review_id,
            "rating": rating,
            "action": action,
        }), 201
    finally:
        conn.close()


@app.route("/api/reviews", methods=["GET"])
def list_reviews():
    """GET /api/reviews — List reviews, optionally filtered by rating."""
    rating = request.args.get("rating", type=int)
    conn = get_db()
    try:
        with _cursor(conn) as cur:
            if rating:
                cur.execute(
                    "SELECT * FROM reviews WHERE rating = %s ORDER BY created_at DESC LIMIT 50",
                    (rating,),
                )
            else:
                cur.execute("SELECT * FROM reviews ORDER BY created_at DESC LIMIT 50")
            rows = cur.fetchall()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return jsonify(rows)
    finally:
        conn.close()


# ===========================================================================
# Abandoned Carts
# ===========================================================================

@app.route("/api/carts/abandoned", methods=["GET"])
def list_abandoned_carts():
    """GET /api/carts/abandoned — List abandoned carts (not recovered, idle > N hours)."""
    hours = request.args.get("hours", 2, type=int)
    conn = get_db()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """SELECT * FROM abandoned_carts
                   WHERE recovered = 0
                     AND last_updated < DATE_SUB(NOW(), INTERVAL %s HOUR)
                   ORDER BY last_updated DESC LIMIT 50""",
                (hours,),
            )
            rows = cur.fetchall()
        for r in rows:
            for dt_field in ("created_at", "last_updated"):
                if r.get(dt_field):
                    r[dt_field] = r[dt_field].isoformat()
            if isinstance(r.get("cart_json"), str):
                r["cart_json"] = json.loads(r["cart_json"])
        return jsonify(rows)
    finally:
        conn.close()


@app.route("/api/carts/save", methods=["POST"])
def save_cart():
    """POST /api/carts/save — Save/update an abandoned cart from the web storefront."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return _err("Missing session_id")

    cart_json = json.dumps(data.get("items", []))
    conn = get_db()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """INSERT INTO abandoned_carts
                   (session_id, customer_phone, customer_email, customer_name, cart_json)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       cart_json = VALUES(cart_json),
                       customer_phone = COALESCE(VALUES(customer_phone), customer_phone),
                       customer_email = COALESCE(VALUES(customer_email), customer_email),
                       customer_name = COALESCE(VALUES(customer_name), customer_name)""",
                (session_id, data.get("customer_phone"), data.get("customer_email"),
                 data.get("customer_name"), cart_json),
            )
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


# ===========================================================================
# Stock Analysis
# ===========================================================================

@app.route("/api/stock/analysis", methods=["GET"])
def stock_analysis():
    """GET /api/stock/analysis — Analyze stock levels and sell-through rates."""
    category = request.args.get("category")
    days = request.args.get("days", 30, type=int)
    low_stock_only = request.args.get("low_stock_only", "false").lower() == "true"
    threshold = request.args.get("threshold", 10, type=int)

    conn = get_db()
    try:
        with _cursor(conn) as cur:
            conditions = []
            params = []
            if category:
                conditions.append("p.category = %s")
                params.append(category)
            if low_stock_only:
                conditions.append("p.stock_qty <= %s")
                params.append(threshold)

            where = " AND ".join(conditions) if conditions else "1=1"
            params.append(days)

            cur.execute(
                f"""SELECT
                        p.id, p.name, p.category, p.size, p.color,
                        p.price, p.stock_qty,
                        COALESCE(SUM(oi.qty), 0) as units_sold,
                        COUNT(DISTINCT oi.order_id) as order_count
                    FROM products p
                    LEFT JOIN order_items oi ON oi.product_id = p.id
                    LEFT JOIN orders o ON o.id = oi.order_id
                        AND o.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                        AND o.status NOT IN ('cancelled', 'refunded')
                    WHERE {where}
                    GROUP BY p.id
                    ORDER BY p.stock_qty ASC""",
                params,
            )
            products = cur.fetchall()

        analysis = []
        alerts = []
        for p in products:
            units_sold = int(p["units_sold"])
            stock = int(p["stock_qty"])
            daily_rate = units_sold / days if days > 0 else 0

            if daily_rate > 0 and stock > 0:
                days_until_stockout = round(stock / daily_rate, 1)
            elif stock == 0:
                days_until_stockout = 0
            else:
                days_until_stockout = None

            suggested_reorder = max(0, round(daily_rate * 30 - stock))

            if stock == 0:
                urgency = "out_of_stock"
            elif days_until_stockout is not None and days_until_stockout <= 3:
                urgency = "critical"
            elif days_until_stockout is not None and days_until_stockout <= 7:
                urgency = "warning"
            elif stock <= threshold:
                urgency = "low"
            else:
                urgency = "healthy"

            item = {
                "product_id": p["id"],
                "name": p["name"],
                "category": p["category"],
                "current_stock": stock,
                "units_sold": units_sold,
                "daily_sell_rate": round(daily_rate, 2),
                "days_until_stockout": days_until_stockout,
                "suggested_reorder": suggested_reorder,
                "urgency": urgency,
                "price": float(p["price"]),
            }
            analysis.append(item)

            if urgency in ("out_of_stock", "critical", "warning"):
                alerts.append({
                    "product_id": p["id"],
                    "name": p["name"],
                    "urgency": urgency,
                    "days_until_stockout": days_until_stockout,
                    "suggested_reorder": suggested_reorder,
                })

        return jsonify({
            "analysis": analysis,
            "alerts": alerts,
            "total_products": len(analysis),
            "critical_count": sum(1 for a in analysis if a["urgency"] in ("out_of_stock", "critical")),
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 404 / 405 handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def handle_404(exc):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(405)
def handle_405(exc):
    return jsonify({"error": "Method not allowed."}), 405


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _ensure_tables()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting Claw Boutique API server on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
