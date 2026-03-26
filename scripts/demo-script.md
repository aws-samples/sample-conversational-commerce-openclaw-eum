# Claw Boutique: End-to-End Demo Script

**Duration:** ~10 minutes
**Prerequisites:** Live AWS deployment, WhatsApp Business number active, SES verified, admin inbox accessible at admin@anycompany.com

---

## Overview

This script walks through every major feature in sequence:

1. Browse the web storefront
2. Trigger cart abandonment recovery via WhatsApp
3. Complete a purchase and verify the stock alert email
4. Check escalation flow and admin action buttons
5. Verify admin email alerts
6. Send a direct WhatsApp message and verify AI responds (browse only, no ordering)
7. Confirm everything is visible in the admin dashboard

---

## Step 1: Browse the Web Storefront

**Time: ~1 min**

1. Open a browser and navigate to: `https://<your-cloudfront-domain>`
2. Verify the page loads with the "Spring / Summer 2026" hero section.
3. Click through the category tabs: **All**, **Tops**, **Dresses**, **Bottoms**, **Accessories**.
   - Each tab filters the product grid without a page reload.
4. Note at least one product with a green "Add to Cart" button (in-stock) and at least one with a grey "Sold Out" badge (stock_qty = 0).

**Expected outcome:** Product catalog loads from the Store API (`https://<your-api-gateway-url>/prod/api/products`). If the API is unavailable, the storefront falls back to mock data. You will still see 16 products but the order step will fail.

---

## Step 2: Add Items to Cart

**Time: ~30 seconds**

1. Click **Add to Cart** on any in-stock product (e.g., "Ribbed Crop Top" or "Pearl Drop Earrings").
2. Verify the amber cart badge in the top-right header updates to show the item count.
3. Verify the toast notification appears briefly at the top of the page (e.g., `"Ribbed Crop Top" added to cart`).
4. Click the **Cart** button to open the slide-over panel.
5. Confirm the item appears with name, color, size, and price.
6. Close the cart panel.

**Expected outcome:** Cart state is persisted to `localStorage`. A `POST /api/carts/save` request fires in the background to record the session on the server. The 2-minute abandonment timer starts.

---

## Step 3: Cart Abandonment Recovery (wait 2+ minutes)

**Time: ~2 min 30 seconds**

> This step requires that the customer's phone number is saved in `localStorage` from a prior checkout, or you can set it manually.

1. Open the browser DevTools console and run:
   ```javascript
   localStorage.setItem('cb_customer_phone', '+15550001234');
   ```
2. Add an item to cart if the cart is empty (the abandonment timer only fires with items present).
3. Wait **at least 2 minutes and 10 seconds** without clicking "Proceed to Checkout".
4. Watch the browser console. You should see `"Abandonment recovery message sent"` logged.
5. Check the WhatsApp on the phone **+65 9720 9504** for an inbound message from the business number (+1 249-209-7349).

**Expected outcome:** A WhatsApp message arrives reading approximately:
> "Hey! We noticed you were eyeing the [product name] at Claw Boutique. Still thinking about it? We'd love to offer you free shipping if you complete your order in the next hour!"

**Note:** The frontend calls `POST /api/carts/notify-abandoned`, which calls `_send_whatsapp()` via the AWS End User Messaging Social API. If the WhatsApp number is not in an active 24-hour conversation window, the message may be blocked by Meta until a template message is used first.

---

## Step 4: Complete a Purchase

**Time: ~1 min**

1. From the storefront, click **Add to Cart** on an in-stock product.
2. Open the cart panel and click **Proceed to Checkout**.
3. Fill in the checkout form:
   - **Full Name:** `Demo Tester`
   - **Email Address:** `test@example.com`
   - **Phone Number:** `+15550001234`
4. Review the order summary on the right side.
5. Click **Place Order**.

**Expected outcome:**
- The order confirmation screen appears with a green checkmark, the order ID (a numeric integer), customer name, and total.
- A `POST /api/orders` request returns HTTP 201 with `{ order_id: N, total: X.XX }`.
- The confirmation page shows the order ID in a pill badge.
- In the background, `_check_stock_and_alert()` runs asynchronously.

**Note the Order ID.** You will need it for Step 5.

---

## Step 5: Verify Stock Alert Email

**Time: ~1 min**

1. Open your admin inbox at `admin@anycompany.com`.
2. Look for an email with subject: `[Claw Boutique] Stock Alert: N item(s) need attention`
   - This arrives within ~30 seconds of the order being placed.
   - It is sent only if any purchased product now has stock_qty = 0, stock_qty <= 5, or is predicted to stock out within 7 days at the current sell rate.
3. Open the email and verify it lists the product(s) purchased with urgency classification (OUT OF STOCK / LOW STOCK).

**Expected outcome:** HTML email from `orders@anycompany.com` with a red header "Claw Boutique: Stock Alert" and at least one amber alert box naming the product.

**If no email arrives:** The purchased product may have sufficient stock (stock_qty > 5 and sell rate is low). Try purchasing a product that already shows low stock, or verify `SELLER_EMAIL` is set to `admin@anycompany.com` in Lambda environment variables.

---

## Step 6: Verify Escalation from Purchase

**Time: ~1 min**

Every purchase triggers a stock alert email (Step 5). Escalations can also be created via the WhatsApp bot when a customer reports a problem, or manually through the admin dashboard.

1. Open the admin dashboard at `https://<your-cloudfront-domain>/admin.html`.
2. Click **Escalations** in the sidebar.
3. If an open escalation exists, you can use the action buttons (Send Apology, Issue Refund, Offer 20% Discount) and click **Resolve**.

**Note:** The storefront no longer has a review form on the order confirmation page. Escalations are created via the API (`POST /api/escalations`) by the WhatsApp bot or programmatically.

---

## Step 7: Admin Email Alerts

**Time: ~1 min**

1. Check your admin inbox (`rsunga@amazon.com`) for stock alert emails from Step 5.
2. Every purchase sends a stock status email with subject: `[Claw Boutique] Stock Alert`.
3. Admin can reply to these emails. The SES receipt rule routes replies to the SNS topic, then Lambda dispatcher, then OpenClaw gateway for processing.

---

## Step 8: Send a WhatsApp Message to the Business Number

**Time: ~2 min**

1. On the phone with number **+15550001234** (or any WhatsApp-capable device), open WhatsApp.
2. Start a new chat with: **+1 249-209-7349**
3. Send the message:
   ```
   Hi, what dresses do you have in size S?
   ```
4. Wait for the AI agent (ClawBot) to respond.

**Expected outcome:** Within 15-30 seconds, ClawBot replies with a list of available dresses in size S pulled from the live product catalog. The response is conversational and includes product names, colors, and prices. ClawBot calls `list_products` with `category=dresses, size=S` under the hood.

5. Follow up with a second message:
   ```
   I'd like to order the Wrap Midi Dress please
   ```
6. ClawBot directs the customer to the storefront to complete the purchase: `https://d22y1hcx8ni0pf.cloudfront.net`

**Verify:** The bot does NOT place orders directly. It helps customers browse and then links them to the storefront for checkout.

---

## Step 9: Admin Dashboard Overview

**Time: ~1 min**

1. Navigate to: `https://<your-cloudfront-domain>/admin.html`
2. The **Dashboard** section loads automatically with 4 stat cards:
   - **Total Orders** should include the order from Step 4.
   - **Pending** should show the Step 4 order as pending.
   - **Revenue** should reflect the order total from Step 4.
   - **Escalations** shows any open escalations from customer reports or WhatsApp issues.
3. Recent orders and open escalations appear below the stat cards.

**Expected outcome:** All data is live from the Store API. The dashboard auto-refreshes every 30 seconds.

---

## Step 10: Manage Orders

**Time: ~1 min**

1. Click **Orders** in the left sidebar.
2. Verify the order from Step 4 appears in the table with:
   - Customer name: Demo Tester
   - Status: pending
   - Total: the amount from Step 4
3. Use the filter tabs (All, Pending, Confirmed, etc.) to filter the order list.
4. Click an order row to open the detail panel. Verify it shows customer info, line items, total, and status.
5. Click **Confirm** on a pending order. A green toast notification appears confirming the status change.
6. Close the detail panel.

**Expected outcome:** Order transitions from "pending" to "confirmed". The status badge updates in both the table and the detail panel.

---

## Step 11: Resolve Escalations

**Time: ~1 min**

1. Click **Escalations** in the left sidebar.
2. Verify at least one open escalation appears with a red border, showing the customer phone and reason.
3. Use the action buttons on the escalation card:
   - **Send Apology via WhatsApp** - sends a personalized apology message
   - **Issue Refund** - processes a refund for the customer
   - **Offer 20% Discount** - generates and sends a discount code
4. Click **Resolve** to mark the escalation as resolved.

**Expected outcome:** Action buttons show a "Done" confirmation after clicking. The Resolve button marks the escalation as resolved and the card updates to show a green "resolved" badge.

---

## Step 12: Review Products

**Time: ~30 sec**

1. Click **Products** in the left sidebar.
2. Verify the product catalog loads with all 20 SKUs.
3. Note any products flagged with a red "Low" stock badge. These match the stock alert from Step 5.

**Expected outcome:** Read-only catalog view with name, category, size, color, price, and current stock levels.

---

## Step 13: Save a Memory

**Time: ~30 sec**

1. Click **Memory** in the left sidebar.
2. Click the **Add Memory** button in the top-right.
3. Fill in:
   - Customer Phone: `+15550001234`
   - Type: `preference`
   - Summary: `Customer prefers size S tops and neutral colors`
   - Tags: `size-preference, repeat-customer`
4. Click **Save Memory**.

**Expected outcome:** A green toast confirms the save. The memory appears in the list below with the phone number, type badge, and summary.

---

## Step 14: Review AI Insights

**Time: ~30 sec**

1. Click **AI Insights** in the left sidebar.
2. The page shows a "ClawBot Daily Analysis" header with the current date and "Powered by Claude" badge.
3. Review the insight cards:
   - **Revenue Summary**: Shows total revenue, order count, and average order value with an optimization recommendation.
   - **Pending Orders**: Warns about unconfirmed orders and suggests a confirmation SLA.
   - **Stock Alert**: Lists out-of-stock and critically low items with reorder suggestions.
   - **Escalations**: Flags unresolved customer complaints with churn risk context.
   - **Category Optimization**: Suggests expanding product lines (e.g., accessories for higher margins).
   - **WhatsApp Engagement**: Recommends broadcast strategies for repeat purchases.

**Expected outcome:** Each card includes a recommendation with actionable advice. Data references (dollar amounts, product counts) come from the live Store API.

**Note:** The insights are generated from real store data at page load. In a production scenario, ClawBot would run this analysis on a daily schedule and surface trends over time.

---

## Timing Summary

| Step | Activity | Duration |
|------|----------|----------|
| 1 | Browse storefront | ~1 min |
| 2 | Add to cart | ~30 sec |
| 3 | Wait for abandonment recovery | ~2 min 30 sec |
| 4 | Complete purchase | ~1 min |
| 5 | Check stock alert email | ~1 min |
| 6 | Verify escalation flow | ~1 min |
| 7 | Admin email alerts | ~1 min |
| 8 | Direct WhatsApp conversation | ~2 min |
| 9 | Admin dashboard overview | ~1 min |
| 10 | Manage orders | ~1 min |
| 11 | Resolve escalations | ~1 min |
| 12 | Review products | ~30 sec |
| 13 | Save a memory | ~30 sec |
| 14 | Review AI insights | ~30 sec |
| **Total** | | **~14 min** |

---

## Troubleshooting Quick Reference

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Products show mock data (IDs like "p1", "p2") | Store API unreachable | Check Lambda function `ClawBoutiqueStoreApi` is deployed and DB is reachable |
| Order placement returns 500 | DB connection error | Verify `DB_SECRET_ARN` in Lambda env and Secrets Manager has correct credentials |
| No stock alert email | Product stock is healthy or `SELLER_EMAIL` unset | Set `SELLER_EMAIL=admin@anycompany.com` in Lambda env |
| No abandonment WhatsApp | Phone not in 24-hour window | Send a message to the business number first to open a window |
| OpenClaw doesn't reply to WhatsApp | Lightsail instance down or token wrong | SSH to Lightsail and check `openclaw` process; check `OPENCLAW_GATEWAY_URL` in Lambda env |
| Admin email reply not processed | SES receipt rule inactive | Run `aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet` |
| Admin dashboard shows all dashes | API CORS error or wrong API URL | Check `config.js` has correct `STORE_API_URL` |
