-- =============================================================================
-- Claw Boutique - Database Schema
-- Target: AWS RDS MySQL 8.0+
-- =============================================================================
-- Run via: mysql -h <host> -u <user> -p <dbname> < schema.sql
-- Or via setup-db.sh which handles env, creation, and seeding automatically.
-- =============================================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET foreign_key_checks = 0;

-- =============================================================================
-- TABLE: customers
-- Stores registered and walk-in customers captured via chat or checkout.
-- Phone is the primary identifier used by the WhatsApp/SMS chat agent.
-- =============================================================================
CREATE TABLE IF NOT EXISTS customers (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key',
    phone       VARCHAR(20)     NOT NULL                        COMMENT 'E.164 format, e.g. +12125550101 — chat agent key',
    email       VARCHAR(254)    NOT NULL DEFAULT ''             COMMENT 'Customer email; empty string when not provided',
    name        VARCHAR(120)    NOT NULL DEFAULT ''             COMMENT 'Display name; may be first name only',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp of first contact',

    PRIMARY KEY (id),

    -- A (phone, email) pair must be globally unique so the same person
    -- cannot be double-inserted regardless of which channel created them.
    UNIQUE KEY uq_customers_phone_email (phone, email),

    -- Fast lookup by phone alone (most common chat-agent query).
    KEY idx_customers_phone (phone),

    -- Fast lookup by email alone (order confirmation / marketing flows).
    KEY idx_customers_email (email)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Registered and transient customers; phone is the canonical chat identifier';


-- =============================================================================
-- TABLE: products
-- Catalog of all sellable items. Each row represents one SKU (size + color
-- combination). A logical "style" (e.g. Oxford Shirt) has multiple rows,
-- one per variant.
-- =============================================================================
CREATE TABLE IF NOT EXISTS products (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key / SKU id',
    name        VARCHAR(200)    NOT NULL                        COMMENT 'Human-readable product name including variant, e.g. "Blue Oxford Shirt - S"',
    description TEXT            NOT NULL                        COMMENT 'Marketing copy shown in chat and storefront',
    category    ENUM('tops','dresses','bottoms','accessories')
                                NOT NULL                        COMMENT 'Top-level browse category used for filtering',
    size        VARCHAR(10)     NOT NULL                        COMMENT 'Size label: XS / S / M / L / XL or numeric waist (28-36)',
    color       VARCHAR(50)     NOT NULL                        COMMENT 'Primary color name, e.g. "Burgundy", "Indigo"',
    price       DECIMAL(10,2)   NOT NULL                        COMMENT 'Retail price in USD',
    stock_qty   SMALLINT UNSIGNED NOT NULL DEFAULT 0            COMMENT 'Current on-hand units; decremented on order placement',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp this SKU was added to the catalog',

    PRIMARY KEY (id),

    -- Composite index supports chat queries like "show me blue dresses in M".
    KEY idx_products_category_size_color (category, size, color),

    -- Price range searches (cheap/expensive filters).
    KEY idx_products_price (price),

    -- Full-text search on name + description for keyword chat queries.
    FULLTEXT KEY ft_products_name_desc (name, description)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Product catalog; one row per SKU (unique size+color variant)';


-- =============================================================================
-- TABLE: orders
-- One row per customer order regardless of channel (chat, web, in-store).
-- An order contains one or more order_items rows.
-- =============================================================================
CREATE TABLE IF NOT EXISTS orders (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key',
    customer_id     INT UNSIGNED    NOT NULL                        COMMENT 'FK -> customers.id',
    status          ENUM('pending','confirmed','processing',
                         'shipped','delivered','cancelled','refunded')
                                    NOT NULL DEFAULT 'pending'      COMMENT 'Lifecycle state; updated by fulfillment webhook or seller',
    channel         ENUM('whatsapp','sms','web','in_store','instagram')
                                    NOT NULL DEFAULT 'whatsapp'     COMMENT 'Sales channel that originated the order',
    total           DECIMAL(10,2)   NOT NULL DEFAULT 0.00           COMMENT 'Order total in USD (sum of qty*unit_price for all items)',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp order was placed',
    shipped_at      DATETIME                 DEFAULT NULL           COMMENT 'UTC timestamp fulfillment carrier scanned the package; NULL until shipped',
    tracking_url    VARCHAR(512)             DEFAULT NULL           COMMENT 'Carrier tracking URL sent to customer; NULL until shipped',

    PRIMARY KEY (id),

    CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_id) REFERENCES customers (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    -- Most common query: "show all pending orders" or "orders for customer X".
    KEY idx_orders_customer_status (customer_id, status),

    -- Time-based order listing for the seller dashboard.
    KEY idx_orders_created_at (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Customer orders; one row per transaction across all channels';


-- =============================================================================
-- TABLE: order_items
-- Line items belonging to an order. Stores unit_price at time of purchase
-- so future price changes do not affect historical orders.
-- =============================================================================
CREATE TABLE IF NOT EXISTS order_items (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key',
    order_id    INT UNSIGNED    NOT NULL                        COMMENT 'FK -> orders.id',
    product_id  INT UNSIGNED    NOT NULL                        COMMENT 'FK -> products.id; preserved for catalog lookups',
    qty         SMALLINT UNSIGNED NOT NULL DEFAULT 1            COMMENT 'Number of units purchased in this line',
    unit_price  DECIMAL(10,2)   NOT NULL                        COMMENT 'Price per unit at time of purchase (snapshot)',

    PRIMARY KEY (id),

    CONSTRAINT fk_order_items_order
        FOREIGN KEY (order_id) REFERENCES orders (id)
        ON UPDATE CASCADE ON DELETE CASCADE,

    CONSTRAINT fk_order_items_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    -- Fast fetch of all line items for a given order (very common).
    KEY idx_order_items_order_id (order_id),

    -- Revenue-by-product analytics query support.
    KEY idx_order_items_product_id (product_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Line items for each order; unit_price is snapshotted at purchase time';


-- =============================================================================
-- TABLE: conversations
-- Ephemeral chat state for the AI shopping agent. One row per customer phone
-- number; upserted on every message turn. Stores the current cart as JSON so
-- the agent can resume a session without re-asking what the customer wants.
-- =============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key',
    customer_phone  VARCHAR(20)     NOT NULL                        COMMENT 'E.164 phone — matches customers.phone; session key',
    intent          VARCHAR(80)              DEFAULT NULL           COMMENT 'Last detected intent label, e.g. "browse", "checkout", "track_order"',
    cart_json       JSON                     DEFAULT NULL           COMMENT 'Current cart: [{product_id, qty, unit_price}, ...]; NULL when cart is empty',
    last_updated    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP     COMMENT 'UTC timestamp of the last message in this session',
    human_handoff   TINYINT(1)      NOT NULL DEFAULT 0              COMMENT '1 = seller has been notified and is taking over; agent should stay silent',

    PRIMARY KEY (id),

    -- One active session per phone number.
    UNIQUE KEY uq_conversations_phone (customer_phone),

    -- TTL-style cleanup query: find sessions idle for > N hours.
    KEY idx_conversations_last_updated (last_updated),

    -- Find all sessions awaiting human handoff.
    KEY idx_conversations_handoff (human_handoff)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='AI agent session state; one row per customer phone; upserted each turn';


-- =============================================================================
-- TABLE: escalations
-- Written whenever the agent cannot handle a request and routes it to the
-- seller. Preserves the full message thread so the seller has context without
-- needing to re-read the raw WhatsApp history.
-- =============================================================================
CREATE TABLE IF NOT EXISTS escalations (
    id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT         COMMENT 'Surrogate primary key',
    customer_phone      VARCHAR(20)     NOT NULL                        COMMENT 'E.164 phone of the customer who triggered the escalation',
    reason              VARCHAR(120)    NOT NULL                        COMMENT 'Short machine label: "out_of_stock", "payment_issue", "custom_request", etc.',
    summary             TEXT            NOT NULL                        COMMENT 'One-paragraph natural-language summary generated by the AI for the seller',
    message_thread      JSON            NOT NULL                        COMMENT 'Array of {role, content, ts} message objects from the session',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp the escalation was created',
    seller_notified     TINYINT(1)      NOT NULL DEFAULT 0              COMMENT '1 = seller notification (email/SMS) has been sent successfully',

    PRIMARY KEY (id),

    -- Find all unacknowledged escalations for the seller dashboard.
    KEY idx_escalations_notified (seller_notified),

    -- Look up escalation history for a specific customer.
    KEY idx_escalations_phone (customer_phone),

    -- Time-ordered listing for the dashboard.
    KEY idx_escalations_created_at (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Seller escalation queue; written when the AI agent cannot resolve a request';


SET foreign_key_checks = 1;
