#!/usr/bin/env python3
"""
update_order_status.py - Update the status of an existing order.

Called by the OpenClaw tool system (Docker sandbox). Reads DB credentials
from environment variables and returns a single JSON object to stdout.

Input  (CLI args):
    --order_id      <str>   (required)
    --new_status    <str>   One of: pending, confirmed, shipped, delivered, cancelled
                            (required)
    --tracking_url  <str>   Required when new_status is "shipped". Optional otherwise.

Output (stdout, JSON):
    {
        "success": bool,
        "status_before": str,
        "status_after": str
    }
    On error: {"error": "<message>"}

Notes:
    - shipped_at is automatically stamped when new_status == "shipped".
    - tracking_url is stored alongside the shipped_at timestamp.
    - Transitions are validated against an allowed list to prevent bad state changes.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pymysql


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid status values for orders
VALID_STATUSES = {"pending", "confirmed", "shipped", "delivered", "cancelled"}

# Allowed forward transitions: status -> set of next allowed statuses
# Backwards / invalid moves are blocked to keep data clean.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"confirmed", "cancelled"},
    "confirmed": {"shipped", "cancelled"},
    "shipped":   {"delivered"},
    "delivered": set(),           # terminal
    "cancelled": set(),           # terminal
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open a pymysql connection using env-based credentials."""
    try:
        conn = pymysql.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            autocommit=False,
        )
        return conn
    except KeyError as exc:
        raise EnvironmentError(f"Missing required environment variable: {exc}") from exc
    except pymysql.MySQLError as exc:
        raise ConnectionError(f"Database connection failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def update_order_status(
    order_id: str,
    new_status: str,
    tracking_url: str | None = None,
) -> dict:
    """
    Update the status field of an order, optionally recording a tracking URL.

    Args:
        order_id:     ID of the order to update.
        new_status:   Target status string.
        tracking_url: Shipping tracking URL. Required when new_status == "shipped".

    Returns:
        dict with 'success', 'status_before', and 'status_after'.

    Raises:
        ValueError: If the order is not found, status is invalid, or transition
                    is not permitted.
        EnvironmentError / ConnectionError: On DB issues.
    """
    order_id = str(order_id).strip()
    new_status = str(new_status).strip().lower()

    if not order_id:
        raise ValueError("order_id must not be empty")

    if new_status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )

    if new_status == "shipped" and not tracking_url:
        raise ValueError("tracking_url is required when setting status to 'shipped'")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Lock the row so concurrent updates don't race
            cur.execute(
                "SELECT status FROM orders WHERE id = %s LIMIT 1 FOR UPDATE",
                (order_id,),
            )
            row = cur.fetchone()

        if not row:
            raise ValueError(f"No order found with id '{order_id}'")

        current_status = row["status"]

        # Guard: no-op if already at target
        if current_status == new_status:
            return {
                "success": True,
                "status_before": current_status,
                "status_after": new_status,
            }

        # Guard: validate transition
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition order from '{current_status}' to '{new_status}'. "
                f"Allowed next statuses: {sorted(allowed) or 'none (terminal state)'}"
            )

        # Build the SET clause dynamically
        now = datetime.now(timezone.utc)
        set_parts = ["status = %s"]
        params: list = [new_status]

        if new_status == "shipped":
            set_parts.append("shipped_at = %s")
            params.append(now)
            set_parts.append("tracking_url = %s")
            params.append(tracking_url)
        elif tracking_url:
            # Allow updating tracking_url on any status if explicitly provided
            set_parts.append("tracking_url = %s")
            params.append(tracking_url)

        params.append(order_id)  # for WHERE clause

        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE orders SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )

        conn.commit()

        return {
            "success": True,
            "status_before": current_status,
            "status_after": new_status,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Update the status of an order")
    parser.add_argument("--order_id", required=True, help="Order ID to update")
    parser.add_argument(
        "--new_status",
        required=True,
        help=f"New status. One of: {', '.join(sorted(VALID_STATUSES))}",
    )
    parser.add_argument(
        "--tracking_url",
        default=None,
        help="Shipping tracking URL (required when new_status=shipped)",
    )
    args = parser.parse_args()

    try:
        result = update_order_status(
            order_id=args.order_id,
            new_status=args.new_status,
            tracking_url=args.tracking_url,
        )
        print(json.dumps(result))
    except (ValueError, EnvironmentError, ConnectionError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"Unexpected error: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
