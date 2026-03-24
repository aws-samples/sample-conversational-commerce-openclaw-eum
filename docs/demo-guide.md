# Demo Guide

Step-by-step walkthrough of every feature in Claw Boutique. Open the storefront and admin dashboard side by side for the best experience.

- **Storefront:** `https://<cloudfront-domain>/`
- **Admin Dashboard:** `https://<cloudfront-domain>/admin.html`

---

## 1. Browse the storefront

Open the storefront URL. You'll see the product catalog with category filters, placeholder images, and pricing.

![Storefront](screenshot-storefront.png)

Click **All**, **Tops**, **Dresses**, **Bottoms**, or **Accessories** to filter. Each product card shows the name, category, size, price, and stock status.

---

## 2. Add a product to cart

Click **Add to Cart** on any product. The cart icon in the top right updates with the item count. Click the cart to review items.

> A 10-second abandonment timer starts when you add an item. If you don't check out in time, a WhatsApp recovery message goes out (see Step 6).

---

## 3. Complete checkout

Click **Checkout**. The form is pre-filled with demo customer details (name, phone, email). Click **Place Order**.

What happens behind the scenes:
- The Store API creates the order in MySQL
- A stock analysis runs. If any purchased product is low or out of stock, the admin gets a stock alert email
- A WhatsApp post-purchase survey is sent to the customer's phone

---

## 4. Check WhatsApp for the post-purchase survey

After checkout, the customer receives a WhatsApp message asking for a 1-5 rating.

![WhatsApp Survey](mockup-wa-survey.png)

If the customer replies with **1 or 2**, an escalation email is sent to the admin and an escalation record is created in the admin dashboard.

---

## 5. See the stock alert email

If the purchased product was low on stock, the admin gets an email like this:

![Stock Alert Email](mockup-email-stock.png)

The email includes current stock levels, daily sell rates, projected days until stockout, and suggested reorder quantities. The admin can reply directly to take action.

---

## 6. Trigger cart abandonment recovery

Go back to the storefront and add a product to cart, but do not check out. Wait 10 seconds. The customer's phone gets a WhatsApp recovery message:

![Cart Recovery WhatsApp](mockup-wa-cart.png)

---

## 7. See the escalation email (negative review)

If the customer left a 1-star rating in the survey (Step 4), the admin gets an escalation email:

![Escalation Email](mockup-email-escalation.png)

The admin can reply to this email with instructions like "offer a 20% discount" or "send a replacement." ClawBot routes the reply through SES inbound to OpenClaw, which follows up with the customer on WhatsApp.

---

## 8. Open the admin dashboard

Switch to the admin dashboard URL. The main page shows real-time stats: total orders, pending orders, revenue, and unresolved escalations.

![Admin Dashboard](screenshot-admin-dashboard.png)

---

## 9. Manage orders

Click **Orders** in the sidebar. You'll see all orders with status filters (All, Pending, Confirmed, Shipped, Delivered, Cancelled).

![Admin Orders](screenshot-admin-orders.png)

Click any order row to open the detail panel on the right. From here you can:
- **Confirm** a pending order
- **Ship** a confirmed order (enter a tracking URL)
- **Mark Delivered** for shipped orders
- **Cancel** any open order

---

## 10. Resolve an escalation

Click **Escalations** in the sidebar. Open escalations show in red. Click **Resolve** to open the resolution modal.

Pick an action (refund issued, replacement shipped, resolved via chat, no action needed), add optional notes, and click **Mark Resolved**.

---

## 11. View products and memory

Click **Products** to see the full catalog with stock levels. Low-stock items are highlighted in red.

Click **Memory** to see saved interaction memories. Click **Add Memory** to manually log a customer interaction (phone, type, summary, resolution, tags).

---

## 12. Check AI Insights

Click **AI Insights** in the sidebar. ClawBot generates a daily analysis based on real store data:

![AI Insights](screenshot-admin-insights.png)

Insights include revenue summary, pending order alerts, stock warnings, escalation reminders, category optimization tips, and WhatsApp engagement suggestions. Each insight has a specific recommendation.

---

## 13. WhatsApp conversation (via OpenClaw)

If the Lightsail instance is running with OpenClaw, you can text the business WhatsApp number directly. The AI agent handles browsing, ordering, and support.

![WhatsApp Order Conversation](mockup-wa-order.png)

The agent browses the catalog, collects customer details, places the order, and confirms, all within WhatsApp.

---

## Running E2E tests

The Playwright test suite covers all of the above automatically:

```bash
cd tests/e2e
npm install
npx playwright install chromium
npx playwright test
```

16 tests run in about 2 minutes. They cover storefront browsing, checkout, stock alerts, WhatsApp survey, review escalation, cart abandonment, and every admin dashboard section.
