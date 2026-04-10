-- =============================================================================
-- Claw Boutique - Schema Additions
-- Adds admin_actions and interaction_memory tables for the admin dashboard
-- and OpenClaw autonomous learning features.
-- Safe to run multiple times (IF NOT EXISTS).
-- =============================================================================

SET NAMES utf8mb4;

-- =============================================================================
-- TABLE: admin_actions
-- Records seller decisions on escalations and other admin actions.
-- =============================================================================
CREATE TABLE IF NOT EXISTS admin_actions (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT      COMMENT 'Surrogate primary key',
    escalation_id   INT UNSIGNED    DEFAULT NULL                 COMMENT 'FK -> escalations.id; NULL for non-escalation actions',
    action_type     VARCHAR(50)     NOT NULL                     COMMENT 'Action category: refund_issued, replacement_shipped, resolved_via_chat, no_action, status_change',
    resolution      TEXT            NOT NULL                     COMMENT 'Free-text description of what was done',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp',

    PRIMARY KEY (id),
    KEY idx_admin_actions_escalation (escalation_id),
    KEY idx_admin_actions_type (action_type),
    KEY idx_admin_actions_created (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Seller admin decisions and actions taken on escalations';


-- =============================================================================
-- TABLE: interaction_memory
-- Stores resolved interaction summaries for OpenClaw to learn from.
-- The AI agent can query this table to find how similar past situations
-- were handled, enabling progressively more autonomous resolution.
-- =============================================================================
CREATE TABLE IF NOT EXISTS interaction_memory (
    id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT      COMMENT 'Surrogate primary key',
    customer_phone      VARCHAR(20)     DEFAULT NULL                 COMMENT 'E.164 phone; NULL for general learnings not tied to a customer',
    interaction_type    VARCHAR(50)     NOT NULL                     COMMENT 'Category: refund_request, wrong_item, shipping_delay, size_exchange, general_inquiry',
    summary             TEXT            NOT NULL                     COMMENT 'What happened — the situation and customer request',
    resolution          TEXT            DEFAULT NULL                 COMMENT 'How it was resolved — the action taken and outcome',
    tags                JSON            DEFAULT NULL                 COMMENT 'Searchable tags: ["refund","wrong_item","resolved"]',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp',

    PRIMARY KEY (id),
    KEY idx_memory_phone (customer_phone),
    KEY idx_memory_type (interaction_type),
    KEY idx_memory_created (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Saved interaction memories for OpenClaw autonomous learning';


-- =============================================================================
-- Add resolved_at and resolved_by columns to escalations if not present
-- =============================================================================
-- MySQL doesn't support IF NOT EXISTS for ALTER TABLE, so we use a procedure
DELIMITER //
CREATE PROCEDURE IF NOT EXISTS add_escalation_columns()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'escalations'
          AND column_name = 'resolved_at'
    ) THEN
        ALTER TABLE escalations
            ADD COLUMN resolved_at DATETIME DEFAULT NULL COMMENT 'UTC timestamp when resolved',
            ADD COLUMN resolution TEXT DEFAULT NULL COMMENT 'Resolution summary from admin';
    END IF;
END //
DELIMITER ;

CALL add_escalation_columns();
DROP PROCEDURE IF EXISTS add_escalation_columns;


-- =============================================================================
-- TABLE: reviews
-- Customer product/order reviews for the review management feature.
-- OpenClaw auto-thanks 5-star and escalates 1-star reviews to the seller.
-- =============================================================================
CREATE TABLE IF NOT EXISTS reviews (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT      COMMENT 'Surrogate primary key',
    customer_phone  VARCHAR(20)     NOT NULL                     COMMENT 'E.164 phone of reviewer',
    customer_name   VARCHAR(120)    NOT NULL                     COMMENT 'Reviewer display name',
    order_id        INT UNSIGNED    DEFAULT NULL                 COMMENT 'FK -> orders.id; NULL if not tied to a specific order',
    rating          TINYINT UNSIGNED NOT NULL                    COMMENT '1-5 star rating',
    review_text     TEXT            NOT NULL                     COMMENT 'Customer review content',
    response_sent   TINYINT(1)     NOT NULL DEFAULT 0            COMMENT '1 = auto-response or seller response has been sent',
    escalated       TINYINT(1)     NOT NULL DEFAULT 0            COMMENT '1 = review was escalated to seller',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp',

    PRIMARY KEY (id),
    KEY idx_reviews_phone (customer_phone),
    KEY idx_reviews_rating (rating),
    KEY idx_reviews_order (order_id),
    KEY idx_reviews_created (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Customer reviews; OpenClaw auto-responds to positive and escalates negative';


-- =============================================================================
-- TABLE: abandoned_carts
-- Tracks web abandoned carts for personalized WhatsApp recovery messages.
-- Populated when a web user adds items to cart; cleared on checkout.
-- =============================================================================
CREATE TABLE IF NOT EXISTS abandoned_carts (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT      COMMENT 'Surrogate primary key',
    session_id      VARCHAR(64)     NOT NULL                     COMMENT 'Browser session ID',
    customer_phone  VARCHAR(20)     DEFAULT NULL                 COMMENT 'E.164 phone if provided during checkout attempt',
    customer_email  VARCHAR(254)    DEFAULT NULL                 COMMENT 'Email if provided',
    customer_name   VARCHAR(120)    DEFAULT NULL                 COMMENT 'Name if provided',
    cart_json       JSON            NOT NULL                     COMMENT 'Cart contents: [{product_id, qty, product_name, price}]',
    recovered       TINYINT(1)     NOT NULL DEFAULT 0            COMMENT '1 = recovery message sent or customer completed checkout',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC when cart was first created',
    last_updated    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'UTC when cart was last modified',

    PRIMARY KEY (id),
    UNIQUE KEY uq_abandoned_carts_session (session_id),
    KEY idx_abandoned_carts_phone (customer_phone),
    KEY idx_abandoned_carts_recovered (recovered),
    KEY idx_abandoned_carts_updated (last_updated)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Web abandoned carts for personalized WhatsApp recovery';
