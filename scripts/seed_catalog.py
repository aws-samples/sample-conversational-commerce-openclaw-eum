#!/usr/bin/env python3
"""
seed_catalog.py — Claw Boutique database seed script
=====================================================
Inserts 20 product SKUs and a handful of test customers into a Lightsail
MySQL database. Safe to run multiple times (idempotent via INSERT IGNORE).

Usage:
    python3 seed_catalog.py

Required environment variables:
    DB_HOST      — Lightsail MySQL endpoint hostname
    DB_USER      — Database user
    DB_PASSWORD  — Database password
    DB_NAME      — Database name (default: claw_boutique)

Optional:
    DB_PORT      — MySQL port (default: 3306)
"""

import os
import sys

# ---------------------------------------------------------------------------
# Dependency check — provide a clear error before a confusing ImportError
# ---------------------------------------------------------------------------
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print("ERROR: mysql-connector-python is not installed.")
    print("       Run: pip install mysql-connector-python")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration (read from environment)
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", "3306")),
    "user":     os.environ.get("DB_USER", ""),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "claw_boutique"),
    "charset":  "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "connection_timeout": 10,
}

if not DB_CONFIG["user"] or not DB_CONFIG["password"]:
    print("ERROR: DB_USER and DB_PASSWORD environment variables must be set.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Product catalog data
# Each tuple: (name, description, category, size, color, price, stock_qty)
# 20 SKUs across 3 base styles with size/color variants, plus accessories.
# ---------------------------------------------------------------------------
PRODUCTS = [
    # --- Oxford Shirt (tops) — 4 size variants ---
    (
        "Oxford Shirt - Sky Blue / S",
        "A crisp, lightweight Oxford-weave button-down in a versatile sky blue. "
        "Easy-iron fabric with a tailored chest pocket.",
        "tops", "S", "Sky Blue", 45.00, 20,
    ),
    (
        "Oxford Shirt - Sky Blue / M",
        "A crisp, lightweight Oxford-weave button-down in a versatile sky blue. "
        "Easy-iron fabric with a tailored chest pocket.",
        "tops", "M", "Sky Blue", 45.00, 25,
    ),
    (
        "Oxford Shirt - Sky Blue / L",
        "A crisp, lightweight Oxford-weave button-down in a versatile sky blue. "
        "Easy-iron fabric with a tailored chest pocket.",
        "tops", "L", "Sky Blue", 45.00, 18,
    ),
    (
        "Oxford Shirt - Sky Blue / XL",
        "A crisp, lightweight Oxford-weave button-down in a versatile sky blue. "
        "Easy-iron fabric with a tailored chest pocket.",
        "tops", "XL", "Sky Blue", 45.00, 10,
    ),

    # --- Floral Wrap Blouse (tops) — 3 size variants ---
    (
        "Floral Wrap Blouse - Ivory / XS",
        "Softly gathered wrap silhouette with an all-over floral print on "
        "ivory chiffon. Adjustable tie waist for a flattering fit.",
        "tops", "XS", "Ivory", 38.00, 12,
    ),
    (
        "Floral Wrap Blouse - Ivory / S",
        "Softly gathered wrap silhouette with an all-over floral print on "
        "ivory chiffon. Adjustable tie waist for a flattering fit.",
        "tops", "S", "Ivory", 38.00, 15,
    ),
    (
        "Floral Wrap Blouse - Ivory / M",
        "Softly gathered wrap silhouette with an all-over floral print on "
        "ivory chiffon. Adjustable tie waist for a flattering fit.",
        "tops", "M", "Ivory", 38.00, 10,
    ),

    # --- Burgundy Midi Dress (dresses) — 4 size variants ---
    (
        "Burgundy Midi Dress / XS",
        "Elegant A-line midi dress in deep burgundy stretch crepe. "
        "Invisible back zip, fully lined, knee-grazing hem.",
        "dresses", "XS", "Burgundy", 89.00, 8,
    ),
    (
        "Burgundy Midi Dress / S",
        "Elegant A-line midi dress in deep burgundy stretch crepe. "
        "Invisible back zip, fully lined, knee-grazing hem.",
        "dresses", "S", "Burgundy", 89.00, 14,
    ),
    (
        "Burgundy Midi Dress / M",
        "Elegant A-line midi dress in deep burgundy stretch crepe. "
        "Invisible back zip, fully lined, knee-grazing hem.",
        "dresses", "M", "Burgundy", 89.00, 12,
    ),
    (
        "Burgundy Midi Dress / L",
        "Elegant A-line midi dress in deep burgundy stretch crepe. "
        "Invisible back zip, fully lined, knee-grazing hem.",
        "dresses", "L", "Burgundy", 89.00, 7,
    ),

    # --- High-Rise Slim Jeans (bottoms) — 4 waist variants ---
    (
        "High-Rise Slim Jeans - Indigo / W28",
        "High-rise slim-leg jeans in premium 12oz indigo denim. "
        "Five-pocket style with a 30-inch inseam.",
        "bottoms", "28", "Indigo", 65.00, 15,
    ),
    (
        "High-Rise Slim Jeans - Indigo / W30",
        "High-rise slim-leg jeans in premium 12oz indigo denim. "
        "Five-pocket style with a 30-inch inseam.",
        "bottoms", "30", "Indigo", 65.00, 20,
    ),
    (
        "High-Rise Slim Jeans - Indigo / W32",
        "High-rise slim-leg jeans in premium 12oz indigo denim. "
        "Five-pocket style with a 30-inch inseam.",
        "bottoms", "32", "Indigo", 65.00, 18,
    ),
    (
        "High-Rise Slim Jeans - Indigo / W34",
        "High-rise slim-leg jeans in premium 12oz indigo denim. "
        "Five-pocket style with a 30-inch inseam.",
        "bottoms", "34", "Indigo", 65.00, 10,
    ),

    # --- Linen Wide-Leg Trousers (bottoms) — 2 color variants ---
    (
        "Linen Wide-Leg Trousers - Ecru / M",
        "Relaxed wide-leg trousers in breathable 100% linen. "
        "Elastic waistband with a drawstring; ideal for warm weather.",
        "bottoms", "M", "Ecru", 55.00, 16,
    ),
    (
        "Linen Wide-Leg Trousers - Slate / M",
        "Relaxed wide-leg trousers in breathable 100% linen. "
        "Elastic waistband with a drawstring; ideal for warm weather.",
        "bottoms", "M", "Slate", 55.00, 14,
    ),

    # --- Accessories — 3 items ---
    (
        "Woven Straw Tote Bag",
        "Handcrafted woven straw tote with leather handles and a cotton "
        "canvas interior pocket. One size fits all.",
        "accessories", "ONE SIZE", "Natural", 48.00, 30,
    ),
    (
        "Silk Square Scarf - Marigold",
        "90cm x 90cm twill silk scarf with a hand-rolled hem and a bold "
        "marigold botanical print. Versatile styling: head, neck, or bag.",
        "accessories", "ONE SIZE", "Marigold", 35.00, 25,
    ),
    (
        "Leather Belt - Cognac",
        "Full-grain cognac leather belt with a brushed-gold pin buckle. "
        "Unisex sizing; available in S/M/L/XL via this single listing.",
        "accessories", "ONE SIZE", "Cognac", 42.00, 22,
    ),
]

assert len(PRODUCTS) == 20, f"Expected 20 products, got {len(PRODUCTS)}"


# ---------------------------------------------------------------------------
# Test customers (for demo / staging use only)
# Each tuple: (phone, email, name)
# ---------------------------------------------------------------------------
TEST_CUSTOMERS = [
    ("+12125550101", "alice@example.com",   "Alice Nguyen"),
    ("+12125550102", "bob@example.com",     "Bob Martinez"),
    ("+12125550103", "carla@example.com",   "Carla Okafor"),
]


# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------
INSERT_PRODUCT_SQL = """
    INSERT IGNORE INTO products
        (name, description, category, size, color, price, stock_qty)
    VALUES
        (%s, %s, %s, %s, %s, %s, %s)
"""

INSERT_CUSTOMER_SQL = """
    INSERT IGNORE INTO customers
        (phone, email, name)
    VALUES
        (%s, %s, %s)
"""

COUNT_SQL = "SELECT COUNT(*) FROM {table}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_connection():
    """Open and return a MySQL connection, exiting on failure."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except MySQLError as exc:
        print(f"ERROR: Could not connect to database: {exc}")
        print(f"       Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
        print(f"       User: {DB_CONFIG['user']}")
        print(f"       DB:   {DB_CONFIG['database']}")
        sys.exit(1)


def count_rows(cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# Main seed logic
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Claw Boutique — Database Seed")
    print("=" * 60)
    print(f"  Host:     {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"  Database: {DB_CONFIG['database']}")
    print()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # ----------------------------------------------------------------
        # Seed products
        # ----------------------------------------------------------------
        print(f"Seeding {len(PRODUCTS)} products...")
        products_before = count_rows(cursor, "products")
        cursor.executemany(INSERT_PRODUCT_SQL, PRODUCTS)
        conn.commit()
        products_after = count_rows(cursor, "products")
        products_inserted = products_after - products_before
        print(f"  Inserted : {products_inserted} new rows  "
              f"(skipped {len(PRODUCTS) - products_inserted} duplicates)")
        print(f"  Total    : {products_after} product rows in DB")

        # ----------------------------------------------------------------
        # Seed test customers
        # ----------------------------------------------------------------
        print(f"\nSeeding {len(TEST_CUSTOMERS)} test customers...")
        customers_before = count_rows(cursor, "customers")
        cursor.executemany(INSERT_CUSTOMER_SQL, TEST_CUSTOMERS)
        conn.commit()
        customers_after = count_rows(cursor, "customers")
        customers_inserted = customers_after - customers_before
        print(f"  Inserted : {customers_inserted} new rows  "
              f"(skipped {len(TEST_CUSTOMERS) - customers_inserted} duplicates)")
        print(f"  Total    : {customers_after} customer rows in DB")

        # ----------------------------------------------------------------
        # Summary of all tables
        # ----------------------------------------------------------------
        print("\n--- Table row counts ---")
        for table in ("customers", "products", "orders", "order_items",
                      "conversations", "escalations"):
            n = count_rows(cursor, table)
            print(f"  {table:<20} {n:>6} rows")

        print("\nSeed complete.")

    except MySQLError as exc:
        conn.rollback()
        print(f"\nERROR during seed: {exc}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
