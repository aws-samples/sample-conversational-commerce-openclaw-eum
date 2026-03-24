# Claw Boutique

AI-powered WhatsApp e-commerce bot built on AWS. Customers text a WhatsApp number to browse products, place orders, and get support. An AI agent (OpenClaw + Claude on Amazon Bedrock) handles conversations automatically. The store owner gets alerts via email and manages everything from an admin dashboard.

---

## Architecture

![Architecture](docs/architecture.drawio.png)

1. Customer sends a WhatsApp message to the business number
2. AWS End User Messaging Social (EUM Social) receives it and publishes to SNS
3. A Lambda dispatcher parses the payload and forwards it to the OpenClaw agent on Lightsail
4. OpenClaw uses Claude on Bedrock to call tools (browse catalog, create order, check stock) against the Store API
5. The reply goes back to the customer via EUM Social

SES handles two-way email with the store owner. Outbound: OpenClaw sends stock alerts and escalation emails. Inbound: the admin replies (e.g., "restock from supplier"), SES routes the reply back through SNS, and OpenClaw acts on it.

The web storefront works in parallel: CloudFront serves the static site from S3, and the frontend calls the same Store API through API Gateway.

### Services used

| Service | What it does |
|---------|-------------|
| EUM Social | Managed WhatsApp Business integration |
| SNS | Event bus for WhatsApp and SES inbound events |
| Lambda (x2) | Dispatcher (routes messages) + Store API (Flask) |
| Lightsail | Hosts OpenClaw agent |
| Bedrock | Claude for AI reasoning |
| API Gateway | REST API for the Store API Lambda |
| MySQL | Products, customers, orders, reviews, carts |
| SES | Admin alert emails + inbound email routing |
| Secrets Manager | Database credentials |
| CloudFront + S3 | Static web storefront and admin dashboard |
| KMS | SNS topic encryption |

### Why these choices

**EUM Social for WhatsApp.** No public endpoints to manage. AWS handles the Meta webhook integration and routes events through SNS with IAM security. The Lightsail OpenClaw blueprint includes EUM Social support out of the box.

**Lightsail for the AI agent.** OpenClaw needs a persistent process for conversation state. Lambda handles the stateless routing, Lightsail handles the stateful agent.

**SES for admin notifications.** Email gives the store owner a formal record. SES receipt rules route replies back into the system, so the admin never has to leave their inbox.

**Intentionally simple.** No ECS, no Fargate, no RDS Multi-AZ. Those make sense at scale but add complexity a solo store owner does not need.

---

## Features

### Order via WhatsApp

Customers browse the catalog, ask questions, and place orders through natural conversation. The AI agent handles the full flow: product search, detail collection, order creation, and confirmation.

<img src="docs/mockup-wa-order.png" width="380" alt="WhatsApp order conversation">

### Post-purchase survey

After checkout, the customer gets a WhatsApp message asking to rate their experience (1-5). Ratings of 1 or 2 automatically create an escalation and send an alert email to the admin.

<img src="docs/mockup-wa-survey.png" width="380" alt="WhatsApp post-purchase survey">

### Cart abandonment recovery

If a customer adds items to cart on the web storefront but does not check out, a WhatsApp message goes out offering free shipping.

<img src="docs/mockup-wa-cart.png" width="380" alt="WhatsApp cart recovery message">

### Stock alerts

Every purchase triggers a background stock analysis. The system calculates daily sell rates and projects days until stockout. When items are out of stock, below 5 units, or predicted to run out within 7 days, the admin gets an email.

<img src="docs/mockup-email-stock.png" width="580" alt="Stock alert email">

### Review escalation

Negative reviews trigger an escalation email with the customer's details, rating, and review text. The admin can reply directly to the email with instructions (e.g., "offer 20% discount"), and ClawBot follows up with the customer on WhatsApp.

<img src="docs/mockup-email-escalation.png" width="580" alt="Review escalation email">

### Admin dashboard

Real-time stats, order management, escalation resolution, product catalog, interaction memory, and AI-generated business insights.

![Admin Dashboard](docs/screenshot-admin-dashboard.png)

![AI Insights](docs/screenshot-admin-insights.png)

### Web storefront

Static site on CloudFront with product browsing, cart, and checkout. Auto-fills demo customer details for quick testing.

![Storefront](docs/screenshot-storefront.png)

---

## Running the demo

See `scripts/demo-script.md` for a step-by-step walkthrough of every feature.

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
  tests/e2e/              Playwright E2E tests
  docs/                   Architecture diagram, screenshots, demo guide
```

---

## Deployment

CDK deploys all AWS resources (SNS, Lambda, SES, S3, CloudFront, API Gateway, Secrets Manager, KMS) in one command. A few manual steps connect WhatsApp and the Lightsail agent.

```bash
git clone <this-repo>
cd claw-boutique
cp .env.example .env          # fill in all values

cd cdk && npm install
npx cdk bootstrap
npx cdk deploy                # save stack outputs
```

After CDK finishes:

1. **Database** - Run `scripts/schema.sql`, `scripts/schema_additions.sql`, and `scripts/seed_catalog.py` against your MySQL instance
2. **Lightsail** - Install OpenClaw, copy `openclaw/` config to `~/.openclaw/`, start the agent bridge
3. **WhatsApp** - Link your WABA phone number to the SNS topic ARN in the EUM Social console
4. **SES** - Activate receipt rules and verify your admin email
5. **Validate** - `./scripts/validate-setup.sh`

---

## License

MIT
