-- =============================================================================
-- Claw Boutique - Demo Data Seed
-- Run by a Custom Resource Lambda after schema creation.
-- Fully idempotent: all inserts use INSERT IGNORE.
-- =============================================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET foreign_key_checks = 0;


-- =============================================================================
-- 1. CUSTOMERS
-- =============================================================================
INSERT IGNORE INTO customers (id, phone, email, name) VALUES
  (1, '+12125550101', 'alice@example.com', 'Alice Nguyen'),
  (2, '+12125550102', 'bob@example.com',   'Bob Martinez'),
  (3, '+12125550103', 'carla@example.com', 'Carla Okafor');


-- =============================================================================
-- 2. PRODUCTS (20 SKUs matching seed_catalog.py exactly)
-- =============================================================================

-- Oxford Shirt - Sky Blue (tops, $45) — IDs 1-4
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (1,  'Oxford Shirt - Sky Blue / S',
       'A crisp, lightweight Oxford-weave button-down in a versatile sky blue. Easy-iron fabric with a tailored chest pocket.',
       'tops', 'S', 'Sky Blue', 45.00, 20),
  (2,  'Oxford Shirt - Sky Blue / M',
       'A crisp, lightweight Oxford-weave button-down in a versatile sky blue. Easy-iron fabric with a tailored chest pocket.',
       'tops', 'M', 'Sky Blue', 45.00, 25),
  (3,  'Oxford Shirt - Sky Blue / L',
       'A crisp, lightweight Oxford-weave button-down in a versatile sky blue. Easy-iron fabric with a tailored chest pocket.',
       'tops', 'L', 'Sky Blue', 45.00, 18),
  (4,  'Oxford Shirt - Sky Blue / XL',
       'A crisp, lightweight Oxford-weave button-down in a versatile sky blue. Easy-iron fabric with a tailored chest pocket.',
       'tops', 'XL', 'Sky Blue', 45.00, 10);

-- Floral Wrap Blouse - Ivory (tops, $38) — IDs 5-7
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (5,  'Floral Wrap Blouse - Ivory / XS',
       'Softly gathered wrap silhouette with an all-over floral print on ivory chiffon. Adjustable tie waist for a flattering fit.',
       'tops', 'XS', 'Ivory', 38.00, 12),
  (6,  'Floral Wrap Blouse - Ivory / S',
       'Softly gathered wrap silhouette with an all-over floral print on ivory chiffon. Adjustable tie waist for a flattering fit.',
       'tops', 'S', 'Ivory', 38.00, 15),
  (7,  'Floral Wrap Blouse - Ivory / M',
       'Softly gathered wrap silhouette with an all-over floral print on ivory chiffon. Adjustable tie waist for a flattering fit.',
       'tops', 'M', 'Ivory', 38.00, 10);

-- Burgundy Midi Dress (dresses, $89) — IDs 8-11
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (8,  'Burgundy Midi Dress / XS',
       'Elegant A-line midi dress in deep burgundy stretch crepe. Invisible back zip, fully lined, knee-grazing hem.',
       'dresses', 'XS', 'Burgundy', 89.00, 8),
  (9,  'Burgundy Midi Dress / S',
       'Elegant A-line midi dress in deep burgundy stretch crepe. Invisible back zip, fully lined, knee-grazing hem.',
       'dresses', 'S', 'Burgundy', 89.00, 14),
  (10, 'Burgundy Midi Dress / M',
       'Elegant A-line midi dress in deep burgundy stretch crepe. Invisible back zip, fully lined, knee-grazing hem.',
       'dresses', 'M', 'Burgundy', 89.00, 12),
  (11, 'Burgundy Midi Dress / L',
       'Elegant A-line midi dress in deep burgundy stretch crepe. Invisible back zip, fully lined, knee-grazing hem.',
       'dresses', 'L', 'Burgundy', 89.00, 7);

-- High-Rise Slim Jeans - Indigo (bottoms, $65) — IDs 12-15
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (12, 'High-Rise Slim Jeans - Indigo / W28',
       'High-rise slim-leg jeans in premium 12oz indigo denim. Five-pocket style with a 30-inch inseam.',
       'bottoms', '28', 'Indigo', 65.00, 15),
  (13, 'High-Rise Slim Jeans - Indigo / W30',
       'High-rise slim-leg jeans in premium 12oz indigo denim. Five-pocket style with a 30-inch inseam.',
       'bottoms', '30', 'Indigo', 65.00, 20),
  (14, 'High-Rise Slim Jeans - Indigo / W32',
       'High-rise slim-leg jeans in premium 12oz indigo denim. Five-pocket style with a 30-inch inseam.',
       'bottoms', '32', 'Indigo', 65.00, 18),
  (15, 'High-Rise Slim Jeans - Indigo / W34',
       'High-rise slim-leg jeans in premium 12oz indigo denim. Five-pocket style with a 30-inch inseam.',
       'bottoms', '34', 'Indigo', 65.00, 10);

-- Linen Wide-Leg Trousers (bottoms, $55) — IDs 16-17
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (16, 'Linen Wide-Leg Trousers - Ecru / M',
       'Relaxed wide-leg trousers in breathable 100% linen. Elastic waistband with a drawstring; ideal for warm weather.',
       'bottoms', 'M', 'Ecru', 55.00, 16),
  (17, 'Linen Wide-Leg Trousers - Slate / M',
       'Relaxed wide-leg trousers in breathable 100% linen. Elastic waistband with a drawstring; ideal for warm weather.',
       'bottoms', 'M', 'Slate', 55.00, 14);

-- Accessories — IDs 18-20
INSERT IGNORE INTO products (id, name, description, category, size, color, price, stock_qty) VALUES
  (18, 'Woven Straw Tote Bag',
       'Handcrafted woven straw tote with leather handles and a cotton canvas interior pocket. One size fits all.',
       'accessories', 'ONE SIZE', 'Natural', 48.00, 30),
  (19, 'Silk Square Scarf - Marigold',
       '90cm x 90cm twill silk scarf with a hand-rolled hem and a bold marigold botanical print. Versatile styling: head, neck, or bag.',
       'accessories', 'ONE SIZE', 'Marigold', 35.00, 25),
  (20, 'Leather Belt - Cognac',
       'Full-grain cognac leather belt with a brushed-gold pin buckle. Unisex sizing; available in S/M/L/XL via this single listing.',
       'accessories', 'ONE SIZE', 'Cognac', 42.00, 22);


-- =============================================================================
-- 3. ORDERS (8 orders spread over the past 30 days)
-- =============================================================================
-- Order 1: Alice, 28 days ago, delivered via web, total $80 (Oxford M $45 + Scarf $35)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at, shipped_at) VALUES
  (1, 1, 'delivered', 'web', 80.00,
   DATE_SUB(NOW(), INTERVAL 28 DAY),
   DATE_SUB(NOW(), INTERVAL 24 DAY));

-- Order 2: Bob, 21 days ago, shipped via whatsapp, total $89 (Burgundy Dress S)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at, shipped_at, tracking_url) VALUES
  (2, 2, 'shipped', 'whatsapp', 89.00,
   DATE_SUB(NOW(), INTERVAL 21 DAY),
   DATE_SUB(NOW(), INTERVAL 17 DAY),
   'https://track.example.com/CB-1002');

-- Order 3: Carla, 18 days ago, delivered via web, total $162 (Jeans W30 $65 + Trousers Ecru $55 + Belt $42)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at, shipped_at) VALUES
  (3, 3, 'delivered', 'web', 162.00,
   DATE_SUB(NOW(), INTERVAL 18 DAY),
   DATE_SUB(NOW(), INTERVAL 14 DAY));

-- Order 4: Alice, 14 days ago, confirmed via whatsapp, total $38 (Floral Blouse S)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at) VALUES
  (4, 1, 'confirmed', 'whatsapp', 38.00,
   DATE_SUB(NOW(), INTERVAL 14 DAY));

-- Order 5: Bob, 10 days ago, processing via web, total $93 (Oxford L $45 + Tote $48)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at) VALUES
  (5, 2, 'processing', 'web', 93.00,
   DATE_SUB(NOW(), INTERVAL 10 DAY));

-- Order 6: Carla, 7 days ago, pending via whatsapp, total $89 (Burgundy Dress M)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at) VALUES
  (6, 3, 'pending', 'whatsapp', 89.00,
   DATE_SUB(NOW(), INTERVAL 7 DAY));

-- Order 7: Alice, 3 days ago, cancelled via web, total $65 (Jeans W28)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at) VALUES
  (7, 1, 'cancelled', 'web', 65.00,
   DATE_SUB(NOW(), INTERVAL 3 DAY));

-- Order 8: Bob, 1 day ago, pending via web, total $90 (Trousers Slate $55 + Scarf $35)
INSERT IGNORE INTO orders (id, customer_id, status, channel, total, created_at) VALUES
  (8, 2, 'pending', 'web', 90.00,
   DATE_SUB(NOW(), INTERVAL 1 DAY));


-- =============================================================================
-- 4. ORDER ITEMS
-- =============================================================================
-- Order 1: Oxford Shirt M (product 2, $45) + Silk Scarf (product 19, $35)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (1,  1, 2,  1, 45.00),
  (2,  1, 19, 1, 35.00);

-- Order 2: Burgundy Midi Dress S (product 9, $89)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (3,  2, 9,  1, 89.00);

-- Order 3: High-Rise Slim Jeans W30 (product 13, $65) + Linen Trousers Ecru (product 16, $55) + Leather Belt (product 20, $42)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (4,  3, 13, 1, 65.00),
  (5,  3, 16, 1, 55.00),
  (6,  3, 20, 1, 42.00);

-- Order 4: Floral Wrap Blouse S (product 6, $38)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (7,  4, 6,  1, 38.00);

-- Order 5: Oxford Shirt L (product 3, $45) + Woven Straw Tote (product 18, $48)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (8,  5, 3,  1, 45.00),
  (9,  5, 18, 1, 48.00);

-- Order 6: Burgundy Midi Dress M (product 10, $89)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (10, 6, 10, 1, 89.00);

-- Order 7: High-Rise Slim Jeans W28 (product 12, $65)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (11, 7, 12, 1, 65.00);

-- Order 8: Linen Wide-Leg Trousers Slate (product 17, $55) + Silk Scarf (product 19, $35)
INSERT IGNORE INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
  (12, 8, 17, 1, 55.00),
  (13, 8, 19, 1, 35.00);


-- =============================================================================
-- 5. REVIEWS (6 reviews tied to orders)
-- =============================================================================
INSERT IGNORE INTO reviews (id, customer_phone, customer_name, order_id, rating, review_text, response_sent, escalated, created_at) VALUES
  (1, '+12125550101', 'Alice Nguyen', 1, 5,
   'Love the Oxford shirt! The fit is perfect and the fabric feels premium. Will definitely order again.',
   1, 0, DATE_SUB(NOW(), INTERVAL 25 DAY)),

  (2, '+12125550102', 'Bob Martinez', 2, 4,
   'Beautiful dress, runs slightly large. I would recommend sizing down. The color is stunning in person.',
   1, 0, DATE_SUB(NOW(), INTERVAL 18 DAY)),

  (3, '+12125550103', 'Carla Okafor', 3, 5,
   'Amazing quality jeans — the denim is thick and well-constructed. The linen trousers are also fantastic for warm days.',
   1, 0, DATE_SUB(NOW(), INTERVAL 15 DAY)),

  (4, '+12125550101', 'Alice Nguyen', 4, 3,
   'Nice blouse but took a while to confirm. The print is pretty but I expected faster order confirmation.',
   0, 0, DATE_SUB(NOW(), INTERVAL 11 DAY)),

  (5, '+12125550102', 'Bob Martinez', 5, 1,
   'Still processing after 10 days, very disappointed. No updates, no communication. Considering cancelling.',
   0, 1, DATE_SUB(NOW(), INTERVAL 3 DAY)),

  (6, '+12125550103', 'Carla Okafor', 6, 4,
   'Gorgeous dress, can''t wait to receive it! Placed the order through WhatsApp and it was super easy.',
   1, 0, DATE_SUB(NOW(), INTERVAL 5 DAY));


-- =============================================================================
-- 6. ESCALATIONS (3 escalations)
-- =============================================================================
-- Escalation 1: Bob, delayed processing, 15 days ago, resolved
INSERT IGNORE INTO escalations
  (id, customer_phone, reason, summary, message_thread, created_at, seller_notified, resolved_at, resolution)
VALUES (
  1,
  '+12125550102',
  'delayed_processing',
  'Customer Bob Martinez (Order #2) reported that his order has been in processing for over a week with no update. He is frustrated and requesting an ETA on shipment. Order is for a Burgundy Midi Dress / S, total $89.',
  '[{"role":"customer","content":"Hi, I ordered a dress 8 days ago and it still shows processing. When will it ship?","ts":"2024-03-20T09:15:00Z"},{"role":"agent","content":"Hi Bob! I apologize for the delay. Let me flag this to our team right away and get you an update shortly.","ts":"2024-03-20T09:15:30Z"},{"role":"customer","content":"It''s been 3 days since you said that and still nothing. I need this for an event next week.","ts":"2024-03-23T14:02:00Z"},{"role":"agent","content":"I completely understand your urgency. I''m escalating this to our seller now to expedite your order.","ts":"2024-03-23T14:02:45Z"}]',
  DATE_SUB(NOW(), INTERVAL 15 DAY),
  1,
  DATE_SUB(NOW(), INTERVAL 13 DAY),
  'Expedited processing, customer notified'
);

-- Escalation 2: Bob, 1-star review, 10 days ago, pending
INSERT IGNORE INTO escalations
  (id, customer_phone, reason, summary, message_thread, created_at, seller_notified, resolved_at, resolution)
VALUES (
  2,
  '+12125550102',
  '1-star review',
  'Customer Bob Martinez left a 1-star review for Order #5 (Oxford Shirt L + Woven Straw Tote, $93). He reports the order has been in "processing" for 10 days with no updates. Customer is expressing intent to cancel and is very dissatisfied. Immediate seller attention required.',
  '[{"role":"customer","content":"I want to leave a review: this is terrible service. My order has been processing for 10 days and nobody has contacted me.","ts":"2024-03-28T16:45:00Z"},{"role":"agent","content":"Bob, I''m very sorry to hear this. Your feedback has been escalated to our team as a priority and we will contact you within the hour.","ts":"2024-03-28T16:45:30Z"}]',
  DATE_SUB(NOW(), INTERVAL 10 DAY),
  1,
  NULL,
  NULL
);

-- Escalation 3: Alice, wrong item received, 5 days ago, resolved
INSERT IGNORE INTO escalations
  (id, customer_phone, reason, summary, message_thread, created_at, seller_notified, resolved_at, resolution)
VALUES (
  3,
  '+12125550101',
  'wrong_item',
  'Customer Alice Nguyen received the wrong size Oxford Shirt in her Order #1. She ordered size M but received size S. She would like the correct size sent and return instructions for the wrong item.',
  '[{"role":"customer","content":"Hi! I got my order but the shirt is size S, I ordered M. Can you help?","ts":"2024-04-01T11:20:00Z"},{"role":"agent","content":"Alice, I''m so sorry about that mix-up! I''m escalating this immediately so we can get the correct size out to you and arrange a return for the S.","ts":"2024-04-01T11:20:40Z"},{"role":"customer","content":"Thank you, I need the M for an event this weekend if possible.","ts":"2024-04-01T11:22:00Z"},{"role":"agent","content":"Understood, I''ve marked this urgent. Our team will reach out to you very shortly with a solution.","ts":"2024-04-01T11:22:30Z"}]',
  DATE_SUB(NOW(), INTERVAL 5 DAY),
  1,
  DATE_SUB(NOW(), INTERVAL 3 DAY),
  'Sent correct size, return label provided'
);


-- =============================================================================
-- 7. ADMIN ACTIONS (3 actions)
-- =============================================================================
INSERT IGNORE INTO admin_actions (id, escalation_id, action_type, resolution, created_at) VALUES
  (1, 1, 'resolved_via_chat',
   'Contacted customer Bob Martinez directly, confirmed order expedited. Dress shipped same day. Customer satisfied with outcome.',
   DATE_SUB(NOW(), INTERVAL 13 DAY)),

  (2, 3, 'replacement_shipped',
   'Shipped correct size M Oxford Shirt to Alice Nguyen via express. Provided prepaid return label for the incorrectly received size S.',
   DATE_SUB(NOW(), INTERVAL 3 DAY)),

  (3, NULL, 'status_change',
   'Updated store hours for holiday schedule: extended hours Friday-Sunday, closed on public holidays. Notified all active chat sessions.',
   DATE_SUB(NOW(), INTERVAL 8 DAY));


-- =============================================================================
-- 8. INTERACTION MEMORY (5 entries)
-- =============================================================================
INSERT IGNORE INTO interaction_memory (id, customer_phone, interaction_type, summary, resolution, tags, created_at) VALUES
  (1, '+12125550102', 'shipping_delay',
   'Customer Bob Martinez reported order stuck in processing for over a week. Escalated to seller who expedited the shipment. Customer accepted the resolution after being notified directly.',
   'Expedited, customer accepted',
   '["shipping","delay","resolved"]',
   DATE_SUB(NOW(), INTERVAL 13 DAY)),

  (2, '+12125550101', 'size_exchange',
   'Customer Alice Nguyen received wrong size Oxford Shirt (received S, ordered M). Seller shipped correct replacement size M with prepaid return label for the wrong item.',
   'Sent replacement',
   '["exchange","wrong_item","resolved"]',
   DATE_SUB(NOW(), INTERVAL 3 DAY)),

  (3, NULL, 'general_inquiry',
   'Multiple customers asking about new arrivals schedule. FAQ needed: new collections drop on the first Monday of each month. Customers want advance notice.',
   NULL,
   '["FAQ","new_arrivals"]',
   DATE_SUB(NOW(), INTERVAL 20 DAY)),

  (4, '+12125550103', 'refund_request',
   'Customer Carla Okafor reported a damaged item on arrival (Linen Wide-Leg Trousers had a torn seam). Customer requested a full refund. Damage confirmed via photo submitted through chat.',
   'Full refund processed',
   '["refund","damage","resolved"]',
   DATE_SUB(NOW(), INTERVAL 6 DAY)),

  (5, NULL, 'general_inquiry',
   'Customers frequently ask about international shipping availability and costs. Question comes up multiple times per week across different customers.',
   'Standard response: we ship to PH, SG, MY',
   '["FAQ","shipping","international"]',
   DATE_SUB(NOW(), INTERVAL 16 DAY));


-- =============================================================================
-- 9. ABANDONED CARTS (2 carts)
-- =============================================================================
-- Cart 1: Alice, Burgundy Midi Dress XS, not recovered
INSERT IGNORE INTO abandoned_carts
  (id, session_id, customer_phone, customer_email, customer_name, cart_json, recovered, created_at, last_updated)
VALUES (
  1,
  'web-abc123',
  '+12125550101',
  'alice@example.com',
  'Alice Nguyen',
  '[{"product_id":8,"qty":1,"product_name":"Burgundy Midi Dress / XS","price":89.00}]',
  0,
  DATE_SUB(NOW(), INTERVAL 4 DAY),
  DATE_SUB(NOW(), INTERVAL 4 DAY)
);

-- Cart 2: Bob (no phone), Oxford Shirt XL + Leather Belt, not recovered
INSERT IGNORE INTO abandoned_carts
  (id, session_id, customer_phone, customer_email, customer_name, cart_json, recovered, created_at, last_updated)
VALUES (
  2,
  'web-def456',
  NULL,
  'bob@example.com',
  'Bob Martinez',
  '[{"product_id":4,"qty":1,"product_name":"Oxford Shirt - Sky Blue / XL","price":45.00},{"product_id":20,"qty":1,"product_name":"Leather Belt - Cognac","price":42.00}]',
  0,
  DATE_SUB(NOW(), INTERVAL 2 DAY),
  DATE_SUB(NOW(), INTERVAL 2 DAY)
);


SET foreign_key_checks = 1;
