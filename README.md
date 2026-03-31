# Claw Boutique

AI-powered WhatsApp e-commerce bot built on AWS. Customers text a WhatsApp number to browse products, place orders, and get support. A Bedrock Agent (Nova Lite) handles conversations in real time. The store owner manages the shop through Telegram: stock alerts, review escalations, and restock commands all flow through a Telegram bot backed by OpenClaw on Lightsail, using Claude on Bedrock for reasoning.

**[See the demo guide](docs/demo-guide.md)** for a step-by-step walkthrough with screenshots.

---

## Architecture

![Architecture](docs/architecture.drawio.png)

Two separate channels, two separate AI models:

**Customer channel (WhatsApp WABA — fast, cheap):**

1. Customer sends a WhatsApp message to the business number
2. EUM Social receives it and publishes to SNS
3. A Lambda dispatcher routes the payload to a Bedrock Agent (Nova Lite)
4. The agent calls tools (browse catalog, create order, check status) against the Store API
5. The reply goes back to the customer via EUM Social

**Seller channel (Telegram — smart, stateful):**

1. The Store API sends stock alerts, review escalations, and order notifications to the seller via the agent-bridge on Lightsail
2. The agent-bridge delivers messages through Telegram using OpenClaw
3. The seller replies in Telegram ("restock 20", "apologize", "mark as shipped")
4. OpenClaw processes the command using Claude on Bedrock, calls the Store API, and confirms back

**Web storefront:**

CloudFront serves the static site from S3, and the frontend calls the Store API through API Gateway.

### Services used

| Service | What it does |
|---------|-------------|
| EUM Social | Managed WhatsApp Business integration (customer channel) |
| Telegram Bot | Seller notifications and command channel |
| SNS | Event bus for WhatsApp inbound events |
| Lambda (x2) | Dispatcher (routes messages) + Store API (Flask) |
| Bedrock Agents | Nova Lite for real-time customer WhatsApp conversations |
| Lightsail | Hosts OpenClaw + agent-bridge (seller channel, memory, insights) |
| Bedrock | Claude Sonnet for OpenClaw reasoning and AI Insights generation |
| API Gateway | REST API for the Store API Lambda |
| MySQL | Products, customers, orders, reviews, carts, memories |
| SES | Customer order confirmation and shipping emails |
| Secrets Manager | Database credentials |
| CloudFront + S3 | Static web storefront and admin dashboard |
| KMS | SNS topic encryption |

### Why these choices

**Bedrock Agent for customer WhatsApp.** The customer-facing chatbot handles structured tasks: catalog search, order placement, surveys. Nova Lite is fast and cheap for high-volume tool-calling. No persistent state needed.

**OpenClaw + Claude for the seller channel.** The seller channel requires judgment: a restock command needs context about which product, a review escalation needs a decision about whether to refund. Claude handles these naturally. OpenClaw provides the persistent process on Lightsail.

**Telegram for seller notifications.** Telegram polling is reliable and stateless — no QR-linked phone, no session files that corrupt on restart. The seller gets a clean conversational interface; OpenClaw gets a stable inbound channel.

**Two models, two jobs.** Nova Lite handles the commodity real-time work cheaply. Claude handles decisions where reasoning quality matters. This keeps costs low for customer traffic while preserving quality for seller-facing actions.

**SES for customer emails.** Transactional email is the right channel for order receipts — archivable, doesn't require the customer to interact.

**Intentionally simple.** No ECS, no Fargate, no RDS Multi-AZ. Those make sense at scale but add complexity a solo store owner does not need.

---

## Features

### Order via WhatsApp

Customers browse the catalog, ask questions, and place orders through natural conversation. A Bedrock Agent (Nova Lite) handles the full flow: product search, detail collection, order creation, and confirmation.

<img src="docs/mockup-wa-order.png" width="380" alt="WhatsApp order conversation">

### Post-purchase survey

After checkout, the customer gets a WhatsApp message asking to rate their experience (1-5). Ratings of 1 or 2 automatically trigger a Telegram alert to the seller and create an escalation record in the admin dashboard.

<img src="docs/mockup-wa-survey.png" width="380" alt="WhatsApp post-purchase survey">

### Cart abandonment recovery

If a customer adds items to cart on the web storefront but does not check out, a WhatsApp message goes out offering free shipping.

<img src="docs/mockup-wa-cart.png" width="380" alt="WhatsApp cart recovery message">

### Stock alerts via Telegram

Every purchase triggers a background stock analysis. The system calculates daily sell rates and projects days until stockout. When items are critical, the seller gets a Telegram alert. They reply with a single command and the restock is processed immediately.

<img src="docs/mockup-tg-stock.png" width="380" alt="Telegram stock alert and restock command">

### Review escalation via Telegram

Negative reviews trigger a Telegram alert with the customer's details, rating, and review text. The seller replies with a short command ("apologize") and OpenClaw sends the apology on WhatsApp, approves the refund, resolves the escalation, and saves the resolution to memory for next time.

<img src="docs/mockup-tg-escalation.png" width="380" alt="Telegram review escalation and apologize command">

### Order confirmation email

Customers receive a confirmation email via SES immediately after placing an order, with a full receipt and shipping notification when the order is marked as shipped.

<img src="docs/mockup-email-confirmation.png" width="560" alt="Order confirmation email">

### Web storefront

Static site on CloudFront with product browsing, cart, and checkout. Auto-fills demo customer details for quick testing.

![Storefront](docs/screenshot-storefront.png)

### Admin dashboard

Real-time stats, order management, escalation resolution, product catalog, interaction memory, and AI-generated business insights.

![Admin Dashboard](docs/screenshot-admin-dashboard.png)

![AI Insights](docs/screenshot-admin-insights.png)

### Memory and learning

After every resolved escalation, OpenClaw calls `save_memory` to record what happened and how it was resolved. Before escalating future issues, it calls `recall_memory` first — if a similar case was handled before, it resolves it autonomously without bothering the seller. The Memory tab in the admin dashboard shows the full log.

---

## Running the demo

**[Demo Guide with screenshots and mocked messages](docs/demo-guide.md)** — step-by-step walkthrough of every feature with inline screenshots of the storefront, admin dashboard, WhatsApp messages, and Telegram alerts.

---

## Project structure

```
claw-boutique/
  cdk/                    CDK stack (SNS, Lambda, SES, S3, CloudFront, API GW)
  lambda/
    dispatcher/           SNS event router (TypeScript)
    store-api/            Flask REST API (Python)
  openclaw/
    openclaw.json         Agent config (model, tools, channels)
    system-prompt.md      ClawBot persona and behavior rules
    tools/                Python tool scripts called by OpenClaw
  web/static/
    index.html            Storefront
    admin.html            Admin dashboard
    js/store.js           Storefront logic
    js/admin.js           Admin dashboard logic
  scripts/
    schema.sql            Database DDL
    seed_catalog.py       Sample product data
  tests/e2e/              Playwright E2E tests + screenshot generation
  docs/                   Architecture diagram, mockups, screenshots, demo guide
```

---

## Deployment

CDK deploys all AWS resources in one command. A few manual steps connect WhatsApp, Telegram, and the Lightsail agent.

```bash
git clone <this-repo>
cd claw-boutique
cp .env.example .env          # fill in all values

cd cdk && npm install
npx cdk bootstrap
npx cdk deploy                # save stack outputs
```

After CDK finishes:

1. **Database** — Run `scripts/schema.sql`, `scripts/schema_additions.sql`, and `scripts/seed_catalog.py` against your MySQL instance
2. **Lightsail** — Install OpenClaw, copy `openclaw/` config to `~/.openclaw/`, start the agent bridge
3. **WhatsApp** — Link your WABA phone number to the SNS topic ARN in the EUM Social console
4. **Telegram** — Create a bot via BotFather, add it to OpenClaw with `openclaw channels add --channel telegram`, send `/start` to the bot from the seller's account
5. **SES** — Verify your sender email for customer order confirmations
6. **Validate** — `./scripts/validate-setup.sh`

---

## License

MIT
