"""
server.py - Flask REST API for the Claw Boutique e-commerce platform.

When running on Lambda, reads DB credentials from Secrets Manager via
DB_SECRET_ARN. Falls back to individual DB_* env vars for local dev.
"""

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime

import boto3
import pymysql
import pymysql.cursors
from flask import Flask, jsonify, request
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_cached_db_config: dict | None = None


def _db_config() -> dict:
    """Build mysql.connector kwargs. Reads from Secrets Manager or env vars."""
    global _cached_db_config
    if _cached_db_config is not None:
        return _cached_db_config

    secret_arn = os.environ.get("DB_SECRET_ARN")
    if secret_arn:
        sm = boto3.client("secretsmanager")
        resp = sm.get_secret_value(SecretId=secret_arn)
        creds = json.loads(resp["SecretString"])
        _cached_db_config = {
            "host": creds["host"],
            "port": int(creds.get("port", 3306)),
            "user": creds["username"],
            "password": creds["password"],
            "database": creds["dbname"],
            "autocommit": False,
            "connect_timeout": 10,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }
    else:
        _cached_db_config = {
            "host": os.environ.get("DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("DB_PORT", 3306)),
            "user": os.environ["DB_USER"],
            "password": os.environ["DB_PASSWORD"],
            "database": os.environ["DB_NAME"],
            "autocommit": False,
            "connect_timeout": 10,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }
    return _cached_db_config


@contextmanager
def get_db():
    """Yield a pymysql connection, committing on success and rolling
    back on any exception. Always closes the connection on exit."""
    conn = pymysql.connect(**_db_config())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cursor(conn, dictionary: bool = True):
    """Return a cursor. pymysql uses DictCursor by default via config."""
    return conn.cursor()


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _err(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _not_found(resource: str = "Resource"):
    return _err(f"{resource} not found.", 404)


# ---------------------------------------------------------------------------
# Async notification helpers (fire-and-forget, never block API response)
# ---------------------------------------------------------------------------

def _send_admin_email(subject: str, html_body: str, text_body: str):
    """Send an email to the seller/admin via SES."""
    from_email = os.environ.get("SES_FROM_EMAIL", "")
    seller_email = os.environ.get("SELLER_EMAIL", "")
    if not from_email or not seller_email:
        logger.warning("SES_FROM_EMAIL or SELLER_EMAIL not set, skipping email")
        return
    try:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        ses.send_email(
            Source=from_email,
            Destination={"ToAddresses": [seller_email]},
            ReplyToAddresses=[from_email],
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("Admin email sent: %s -> %s", subject, seller_email)
    except Exception:
        logger.exception("Failed to send admin email: %s", subject)


def _send_whatsapp(phone: str, text: str):
    """Send a WhatsApp text message via EUMS."""
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    if not phone_number_id:
        logger.warning("WHATSAPP_PHONE_NUMBER_ID not set, skipping WhatsApp")
        return
    if not phone.startswith("+"):
        p = "+" + phone
    else:
        p = phone
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": p,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    try:
        client = boto3.client(
            "socialmessaging",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        client.send_whatsapp_message(
            originationPhoneNumberId=phone_number_id,
            message=json.dumps(payload).encode("utf-8"),
            metaApiVersion="v21.0",
        )
        logger.info("WhatsApp sent to %s", p)
    except Exception:
        logger.exception("Failed to send WhatsApp to %s", p)


def _send_order_survey(phone: str, name: str, order_id: int, item_names: list[str]):
    """Send a WhatsApp post-purchase survey asking for a 1-5 rating."""
    items_text = ", ".join(item_names) if item_names else "your items"
    message = (
        f"Hi {name}! Thanks for your Claw Boutique order (#{order_id}). "
        f"We'd love your feedback on {items_text}.\n\n"
        f"How would you rate your experience? Reply with a number from 1 to 5:\n"
        f"  1 = Very poor\n"
        f"  2 = Poor\n"
        f"  3 = Okay\n"
        f"  4 = Good\n"
        f"  5 = Excellent"
    )
    _send_whatsapp(phone, message)


def _check_stock_and_alert(product_ids: list[int]):
    """After an order, check if any purchased products are now low stock and email admin."""
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                fmt = ",".join(["%s"] * len(product_ids))
                cur.execute(
                    f"""SELECT p.id, p.name, p.stock_qty, p.category, p.size, p.color,
                               COALESCE(SUM(oi.qty), 0) as units_sold_30d
                        FROM products p
                        LEFT JOIN order_items oi ON oi.product_id = p.id
                        LEFT JOIN orders o ON o.id = oi.order_id
                            AND o.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                            AND o.status NOT IN ('cancelled', 'refunded')
                        WHERE p.id IN ({fmt})
                        GROUP BY p.id""",
                    product_ids,
                )
                rows = cur.fetchall()

        alerts = []
        for r in rows:
            stock = int(r["stock_qty"])
            sold = int(r["units_sold_30d"])
            daily_rate = sold / 30.0 if sold > 0 else 0
            if daily_rate > 0 and stock > 0:
                days_left = round(stock / daily_rate, 1)
            else:
                days_left = 0 if stock == 0 else None

            if stock == 0:
                alerts.append(f"OUT OF STOCK: {r['name']} ({r['category']}, {r['size']}, {r['color']})")
            elif days_left is not None and days_left <= 7:
                reorder = max(0, round(daily_rate * 30 - stock))
                alerts.append(
                    f"LOW STOCK: {r['name']} — {stock} units left, "
                    f"~{days_left} days until stockout at current rate "
                    f"({daily_rate:.1f}/day). Suggest reorder: {reorder} units."
                )
            elif stock <= 5:
                alerts.append(f"LOW STOCK: {r['name']} — only {stock} units remaining")

        # Always send a stock report after a purchase (for demo visibility)
        if not alerts:
            for r in rows:
                stock = int(r["stock_qty"])
                sold = int(r["units_sold_30d"])
                daily_rate = sold / 30.0 if sold > 0 else 0
                alerts.append(
                    f"OK: {r['name']} — {stock} units in stock"
                    + (f" ({daily_rate:.1f}/day sell rate)" if daily_rate > 0 else "")
                )

        alert_text = "\n\n".join(alerts)
        has_issues = any(a.startswith("OUT OF STOCK") or a.startswith("LOW STOCK") for a in alerts)
        if has_issues:
            subject = f"[Claw Boutique] Stock Alert: {sum(1 for a in alerts if not a.startswith('OK'))} item(s) need attention"
        else:
            subject = f"[Claw Boutique] Stock Report: {len(rows)} item(s) after purchase"

        color_map = {"OUT OF STOCK": ("#fde8e8", "#e53e3e", "red"), "LOW STOCK": ("#fff3cd", "#ffc107", "amber"), "OK": ("#e8f5e9", "#38a169", "green")}
        def _alert_box(a):
            key = a.split(":")[0]
            bg, border, _ = color_map.get(key, ("#f0f0f0", "#ccc", "grey"))
            return f'<div style="background:{bg};border:1px solid {border};border-radius:8px;padding:12px;margin:8px 0"><strong>{key}</strong>: {":".join(a.split(":")[1:])}</div>'

        html = f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<h2 style="color:{'#c0392b' if has_issues else '#38a169'}">Claw Boutique — {'Stock Alert' if has_issues else 'Stock Report'}</h2>
<p>{'The following items need your attention after a recent purchase:' if has_issues else 'Stock levels after a recent purchase:'}</p>
{"".join(_alert_box(a) for a in alerts)}
<p style="margin-top:20px;color:#888;font-size:12px">Automated alert from Claw Boutique AI</p>
</body></html>"""
        _send_admin_email(subject, html, f"Stock Report\n\n{alert_text}")
    except Exception:
        logger.exception("Stock check failed")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def list_products():
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


@app.route("/api/products/<int:product_id>", methods=["PATCH"])
def update_product(product_id):
    data = request.get_json(silent=True) or {}
    allowed = {"stock_qty", "price", "name", "description"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return _err("No valid fields to update", 400)
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [product_id]
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(f"UPDATE products SET {set_clause} WHERE id = %s", values)
                conn.commit()
    except Exception as exc:
        logger.exception("update_product error")
        return _err(str(exc), 500)
    return jsonify({"ok": True, "updated": list(updates.keys())})


@app.route("/api/products/reset-stock", methods=["POST"])
def reset_stock():
    data = request.get_json(silent=True) or {}
    qty = int(data.get("stock_qty", 5))
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute("UPDATE products SET stock_qty = %s", (qty,))
                conn.commit()
                count = cur.rowcount
    except Exception as exc:
        logger.exception("reset_stock error")
        return _err(str(exc), 500)
    return jsonify({"ok": True, "products_updated": count, "stock_qty": qty})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

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

                product_ids = [item["product_id"] for item in items]
                fmt = ",".join(["%s"] * len(product_ids))
                cur.execute(
                    f"SELECT id, name, price, stock_qty FROM products WHERE id IN ({fmt}) FOR UPDATE",
                    product_ids,
                )
                product_rows = {r["id"]: r for r in cur.fetchall()}

                missing = [pid for pid in product_ids if pid not in product_rows]
                if missing:
                    raise ValueError(f"Product(s) not found: {missing}")

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

    # Fire-and-forget: check stock levels and alert admin if low
    _check_stock_and_alert(product_ids)

    # Fire-and-forget: send WhatsApp survey to customer
    if customer_phone:
        item_names = [product_rows[pid]["name"] for pid in list(qty_map.keys())[:3] if pid in product_rows and "name" in product_rows[pid]]
        _send_order_survey(customer_phone, customer_name, order_id, item_names)

    return jsonify({"order_id": order_id, "total": round(total, 2)}), 201


@app.route("/api/orders", methods=["GET"])
def list_orders():
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
    body = request.get_json(silent=True)
    if not body:
        return _err("Request body must be JSON.")

    new_status = (body.get("new_status") or body.get("status") or "").strip()
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
    resolved_param = request.args.get("resolved", "").strip().lower()

    conditions = []
    params = []

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


@app.route("/api/escalations/<int:escalation_id>/send-apology", methods=["POST"])
def send_apology_whatsapp(escalation_id: int):
    """Send a WhatsApp apology + refund message and resolve the escalation."""
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    "SELECT id, customer_phone, reason, summary FROM escalations WHERE id = %s LIMIT 1",
                    (escalation_id,),
                )
                esc = cur.fetchone()
                if not esc:
                    return _not_found("Escalation")

                # Use phone from body or from escalation record
                dest_phone = phone or (esc.get("customer_phone") or "")
                if not dest_phone:
                    return _err("No customer phone available for this escalation.")

                message = (
                    "Hi, this is Claw Boutique. We sincerely apologize for your recent experience. "
                    "We've processed a full refund for your order. "
                    "We value your feedback and are working to improve. "
                    "Please don't hesitate to reach out if there's anything else we can help with."
                )
                _send_whatsapp(dest_phone, message)

                # Resolve the escalation
                cur.execute(
                    """INSERT INTO admin_actions
                        (escalation_id, action_type, resolution, created_at)
                    VALUES (%s, %s, %s, %s)""",
                    (escalation_id, "apology_refund", "Sent apology & refund via WhatsApp", datetime.utcnow()),
                )
                action_id = cur.lastrowid
    except Exception as exc:
        logger.exception("send_apology_whatsapp error")
        return _err(str(exc), 500)

    return jsonify({
        "escalation_id": escalation_id,
        "action_id": action_id,
        "phone": dest_phone,
        "message_sent": True,
    }), 200


# ---------------------------------------------------------------------------
# Admin email reply actions
# ---------------------------------------------------------------------------

@app.route("/api/admin/email-action", methods=["POST"])
def admin_email_action():
    """Process an admin email reply to a stock alert or negative review alert.

    The dispatcher calls this endpoint when it detects an admin reply to one of
    the automated alert emails.  The request body contains:
      - action: "restock" | "send_apology"
      - For restock: product_name, qty (optional, default 20)
      - For send_apology: customer_phone, customer_name (optional)
    """
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()

    if action == "restock":
        product_name = (data.get("product_name") or "").strip()
        qty = int(data.get("qty", 20))
        if not product_name:
            return _err("product_name is required for restock action")
        try:
            with get_db() as conn:
                with _cursor(conn) as cur:
                    # Fuzzy match: find product whose name contains the search term
                    cur.execute(
                        "SELECT id, name, stock_qty FROM products WHERE name LIKE %s LIMIT 1",
                        (f"%{product_name}%",),
                    )
                    product = cur.fetchone()
                    if not product:
                        return _err(f"No product found matching '{product_name}'", 404)

                    new_stock = int(product["stock_qty"]) + qty
                    cur.execute(
                        "UPDATE products SET stock_qty = %s WHERE id = %s",
                        (new_stock, product["id"]),
                    )
                    conn.commit()
        except Exception as exc:
            logger.exception("admin restock error")
            return _err(str(exc), 500)

        # Send confirmation email
        subject = f"[Claw Boutique] Restock Confirmed: {product['name']}"
        html = f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#38a169">Claw Boutique — Restock Confirmed</h2>
<p>Your restock request has been processed:</p>
<div style="background:#e8f5e9;border:1px solid #38a169;border-radius:8px;padding:12px;margin:8px 0">
<strong>{product['name']}</strong> — added {qty} units (new total: {new_stock})
</div>
<p style="margin-top:20px;color:#888;font-size:12px">Automated confirmation from Claw Boutique AI</p>
</body></html>"""
        text = f"Restock Confirmed: {product['name']} — added {qty} units (new total: {new_stock})"
        _send_admin_email(subject, html, text)

        return jsonify({
            "action": "restock",
            "product_id": product["id"],
            "product_name": product["name"],
            "qty_added": qty,
            "new_stock": new_stock,
        })

    elif action == "send_apology":
        phone = (data.get("customer_phone") or "").strip()
        customer_name = (data.get("customer_name") or "").strip()
        if not phone:
            return _err("customer_phone is required for send_apology action")

        message = (
            "Hi" + (f" {customer_name}" if customer_name else "") + ", this is Claw Boutique. "
            "We sincerely apologize for your recent experience. "
            "We've processed a full refund for your order. "
            "We value your feedback and are working to improve. "
            "Please don't hesitate to reach out if there's anything else we can help with."
        )
        _send_whatsapp(phone, message)

        # Resolve any open escalation for this customer
        resolved_id = None
        try:
            with get_db() as conn:
                with _cursor(conn) as cur:
                    cur.execute(
                        """SELECT e.id FROM escalations e
                           LEFT JOIN admin_actions a ON a.escalation_id = e.id
                           WHERE e.customer_phone = %s AND a.id IS NULL
                           ORDER BY e.created_at DESC LIMIT 1""",
                        (phone,),
                    )
                    esc = cur.fetchone()
                    if esc:
                        cur.execute(
                            """INSERT INTO admin_actions
                                (escalation_id, action_type, resolution, created_at)
                            VALUES (%s, %s, %s, %s)""",
                            (esc["id"], "apology_refund", "Admin replied to alert email: sent apology & refund via WhatsApp", datetime.utcnow()),
                        )
                        resolved_id = esc["id"]
        except Exception:
            logger.exception("Failed to resolve escalation for %s", phone)

        # Send confirmation email
        display = f"{customer_name} ({phone})" if customer_name else phone
        subject = f"[Claw Boutique] Apology & Refund Sent to {display}"
        html = f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#38a169">Claw Boutique — Action Confirmed</h2>
<p>Your request has been processed:</p>
<div style="background:#e8f5e9;border:1px solid #38a169;border-radius:8px;padding:12px;margin:8px 0">
<strong>Apology &amp; refund sent via WhatsApp</strong> to {display}
</div>
{f'<p>Escalation #{resolved_id} has been marked as resolved.</p>' if resolved_id else ''}
<p style="margin-top:20px;color:#888;font-size:12px">Automated confirmation from Claw Boutique AI</p>
</body></html>"""
        text = f"Apology & refund sent via WhatsApp to {display}" + (f". Escalation #{resolved_id} resolved." if resolved_id else "")
        _send_admin_email(subject, html, text)

        return jsonify({
            "action": "send_apology",
            "phone": phone,
            "whatsapp_sent": True,
            "escalation_resolved": resolved_id,
        })

    else:
        return _err(f"Unknown action: '{action}'. Expected 'restock' or 'send_apology'.")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats", methods=["GET"])
def get_stats():
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
    customer_phone = request.args.get("customer_phone", "").strip() or None
    interaction_type = request.args.get("interaction_type", "").strip() or None
    search = request.args.get("search", "").strip() or None
    limit = request.args.get("limit", 100, type=int)

    conditions = []
    params = []

    if customer_phone:
        conditions.append("customer_phone = %s")
        params.append(customer_phone)
    if interaction_type:
        conditions.append("interaction_type = %s")
        params.append(interaction_type)
    if search:
        conditions.append("(summary LIKE %s OR resolution LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT id, customer_phone, interaction_type, summary, resolution, tags, created_at
        FROM interaction_memory
        {where}
        ORDER BY created_at DESC
        LIMIT %s
    """
    params.append(limit)

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


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@app.route("/api/reviews", methods=["POST"])
def create_review():
    data = request.get_json(silent=True) or {}
    required = ("customer_phone", "customer_name", "rating", "review_text")
    for field in required:
        if field not in data:
            return _err(f"Missing required field: {field}")

    rating = int(data["rating"])
    if rating < 1 or rating > 5:
        return _err("Rating must be between 1 and 5")

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """INSERT INTO reviews
                       (customer_phone, customer_name, order_id, rating, review_text)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (data["customer_phone"], data["customer_name"],
                     data.get("order_id"), rating, data["review_text"]),
                )
                review_id = cur.lastrowid
    except Exception as exc:
        logger.exception("create_review error")
        return _err(str(exc), 500)

    if rating >= 4:
        action = "auto_thank"
    elif rating == 3:
        action = "follow_up"
    else:
        action = "escalate"
        # Send escalation email to admin for low ratings
        subject = f"[Claw Boutique] Negative Review Alert — {rating} star from {data['customer_name']}"
        html = f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#c0392b">Claw Boutique — Negative Review Alert</h2>
<p>A customer has left a <strong>{rating}-star review</strong> that requires your attention.</p>
<table style="width:100%;border-collapse:collapse">
  <tr><td style="padding:8px;border-bottom:1px solid #eee"><strong>Customer</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{data['customer_name']} ({data['customer_phone']})</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee"><strong>Rating</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{"&#11088;" * rating}{"&#9734;" * (5-rating)} ({rating}/5)</td></tr>
  <tr><td style="padding:8px"><strong>Review</strong></td>
      <td style="padding:8px">{data['review_text']}</td></tr>
</table>
<p style="margin-top:20px;color:#c0392b;font-weight:bold">Please follow up with this customer as soon as possible.</p>
<p style="color:#888;font-size:12px">Automated alert from Claw Boutique AI</p>
</body></html>"""
        text = (
            f"Negative Review Alert\n\n"
            f"Customer: {data['customer_name']} ({data['customer_phone']})\n"
            f"Rating: {rating}/5\n"
            f"Review: {data['review_text']}\n\n"
            f"Please follow up with this customer."
        )
        _send_admin_email(subject, html, text)

    return jsonify({
        "review_id": review_id,
        "rating": rating,
        "action": action,
    }), 201


@app.route("/api/reviews/from-whatsapp", methods=["POST"])
def create_review_from_whatsapp():
    """Handle a review rating reply from WhatsApp.

    Looks up the most recent order for the given phone number and submits
    the review on behalf of the customer.  Expects: {phone, rating}.
    """
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    rating_raw = data.get("rating")

    if not phone or rating_raw is None:
        return _err("Missing required fields: phone, rating")

    try:
        rating = int(rating_raw)
    except (ValueError, TypeError):
        return _err("Rating must be a number 1-5")

    if rating < 1 or rating > 5:
        return _err("Rating must be between 1 and 5")

    # Look up most recent order for this phone (join customers table)
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """SELECT o.id, c.name AS customer_name, c.phone AS customer_phone
                       FROM orders o
                       JOIN customers c ON c.id = o.customer_id
                       WHERE c.phone = %s
                       ORDER BY o.created_at DESC LIMIT 1""",
                    (phone,),
                )
                order = cur.fetchone()
    except Exception as exc:
        logger.exception("from-whatsapp review lookup error")
        return _err(str(exc), 500)

    if not order:
        return _err(f"No orders found for phone {phone}", 404)

    # Build review text from rating
    rating_labels = {1: "Very poor", 2: "Poor", 3: "Okay", 4: "Good", 5: "Excellent"}
    review_text = f"WhatsApp survey reply: {rating_labels.get(rating, str(rating))}"

    customer_name = order["customer_name"]

    # Insert review
    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    """INSERT INTO reviews
                       (customer_phone, customer_name, order_id, rating, review_text)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (phone, customer_name, order["id"], rating, review_text),
                )
                review_id = cur.lastrowid
    except Exception as exc:
        logger.exception("from-whatsapp review insert error")
        return _err(str(exc), 500)

    action = "auto_thank" if rating >= 4 else "follow_up" if rating == 3 else "escalate"

    if action == "escalate":
        subject = f"[Claw Boutique] Negative Review Alert: {rating} star from {customer_name}"
        html = f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#c0392b">Claw Boutique: Negative Review Alert</h2>
<p>A customer has left a <strong>{rating}-star review</strong> via WhatsApp that requires your attention.</p>
<table style="width:100%;border-collapse:collapse">
  <tr><td style="padding:8px;border-bottom:1px solid #eee"><strong>Customer</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{customer_name} ({phone})</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee"><strong>Rating</strong></td>
      <td style="padding:8px;border-bottom:1px solid #eee">{"&#11088;" * rating}{"&#9734;" * (5-rating)} ({rating}/5)</td></tr>
  <tr><td style="padding:8px"><strong>Review</strong></td>
      <td style="padding:8px">{review_text}</td></tr>
</table>
<p style="margin-top:20px;color:#c0392b;font-weight:bold">Please follow up with this customer as soon as possible.</p>
</body></html>"""
        text = (
            f"Negative Review Alert\n\n"
            f"Customer: {customer_name} ({phone})\n"
            f"Rating: {rating}/5\n"
            f"Review: {review_text}\n\n"
            f"Please follow up with this customer."
        )
        _send_admin_email(subject, html, text)

        # Also create an escalation so it appears on the dashboard
        try:
            with get_db() as conn:
                with _cursor(conn) as cur:
                    cur.execute(
                        """INSERT INTO escalations
                            (customer_phone, reason, summary, seller_notified, created_at)
                        VALUES (%s, %s, %s, %s, %s)""",
                        (phone, f"{rating}-star review",
                         f"{customer_name} rated {rating}/5: {review_text}",
                         1, datetime.utcnow()),
                    )
        except Exception as exc:
            logger.exception("from-whatsapp escalation insert error")

    return jsonify({
        "review_id": review_id,
        "rating": rating,
        "action": action,
        "customer_name": customer_name,
        "order_id": order["id"],
    }), 201


@app.route("/api/reviews", methods=["GET"])
def list_reviews():
    rating = request.args.get("rating", type=int)

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                if rating:
                    cur.execute(
                        "SELECT * FROM reviews WHERE rating = %s ORDER BY created_at DESC LIMIT 50",
                        (rating,),
                    )
                else:
                    cur.execute("SELECT * FROM reviews ORDER BY created_at DESC LIMIT 50")
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_reviews error")
        return _err(str(exc), 500)

    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return jsonify(rows)


# ---------------------------------------------------------------------------
# Abandoned Carts
# ---------------------------------------------------------------------------

@app.route("/api/carts/abandoned", methods=["GET"])
def list_abandoned_carts():
    hours = request.args.get("hours", 2, type=int)
    customer_phone = request.args.get("customer_phone", "").strip() or None

    conditions = ["recovered = 0", "last_updated < DATE_SUB(NOW(), INTERVAL %s HOUR)"]
    params: list = [hours]

    if customer_phone:
        conditions.append("customer_phone = %s")
        params.append(customer_phone)

    where = " AND ".join(conditions)

    try:
        with get_db() as conn:
            with _cursor(conn) as cur:
                cur.execute(
                    f"""SELECT * FROM abandoned_carts
                       WHERE {where}
                       ORDER BY last_updated DESC LIMIT 50""",
                    params,
                )
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("list_abandoned_carts error")
        return _err(str(exc), 500)

    for r in rows:
        for dt_field in ("created_at", "last_updated"):
            if r.get(dt_field):
                r[dt_field] = r[dt_field].isoformat()
        if isinstance(r.get("cart_json"), str):
            r["cart_json"] = json.loads(r["cart_json"])
    return jsonify(rows)


@app.route("/api/carts/notify-abandoned", methods=["POST"])
def notify_abandoned_cart():
    """Send a WhatsApp recovery message for an abandoned cart."""
    data = request.get_json(silent=True) or {}
    phone = (data.get("customer_phone") or "").strip()
    items = data.get("items", [])

    if not phone:
        return _err("customer_phone is required")
    if not items:
        return _err("items list is required")

    # Build a personalized recovery message
    item_names = [i.get("name", "item") for i in items[:3]]
    if len(items) > 3:
        items_text = ", ".join(item_names) + f" and {len(items) - 3} more"
    else:
        items_text = " and ".join(item_names) if len(item_names) <= 2 else ", ".join(item_names[:-1]) + " and " + item_names[-1]

    message = (
        f"Hey! We noticed you were eyeing the {items_text} at Claw Boutique. "
        f"Still thinking about it? We'd love to offer you free shipping if you "
        f"complete your order in the next hour! Just reply here or visit our store."
    )

    _send_whatsapp(phone, message)

    return jsonify({"success": True, "message_preview": message[:100] + "..."})


@app.route("/api/carts/save", methods=["POST"])
def save_cart():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return _err("Missing session_id")

    cart_json = json.dumps(data.get("items", []))

    try:
        with get_db() as conn:
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
    except Exception as exc:
        logger.exception("save_cart error")
        return _err(str(exc), 500)

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Stock Analysis
# ---------------------------------------------------------------------------

@app.route("/api/stock/analysis", methods=["GET"])
def stock_analysis():
    category = request.args.get("category")
    days = request.args.get("days", 30, type=int)
    low_stock_only = request.args.get("low_stock_only", "false").lower() == "true"
    threshold = request.args.get("threshold", 10, type=int)

    try:
        with get_db() as conn:
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
    except Exception as exc:
        logger.exception("stock_analysis error")
        return _err(str(exc), 500)

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


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def handle_404(exc):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(405)
def handle_405(exc):
    return jsonify({"error": "Method not allowed."}), 405


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting Claw Boutique API server on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
