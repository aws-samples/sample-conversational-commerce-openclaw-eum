# Claw Boutique

AI-powered WhatsApp e-commerce bot built on AWS. Customers browse and order through a web storefront, then receive WhatsApp messages and emails for order confirmation, surveys, and refunds. The store owner manages everything through Telegram, where an AI agent (Claude on EKS) handles restock, refund, and order commands.

![Architecture](docs/architecture.drawio.png)

## How it works

Two AI models, two channels:

- **Customer channel (WhatsApp)** -- A Bedrock Agent (Nova Lite) handles real-time conversations. Customer messages arrive via End User Messaging Social, route through SNS to a Dispatcher Lambda, and get processed by the agent. Fast and cheap for high-volume tool-calling.
- **Seller channel (Telegram)** -- OpenClaw runs Claude on EKS. The store owner receives stock alerts, review escalations, and order notifications on Telegram. They reply with commands like "restock", "apologize", or "ship order 42", and ClawBot executes them.
- **Web storefront** -- CloudFront serves a static site from S3. Checkout calls the Store API through API Gateway.

All three channels share the same Store API Lambda and RDS MySQL database.

### Services used

| Service | Role |
|---------|------|
| End User Messaging Social | Managed WhatsApp Business integration |
| Telegram Bot API | Seller notification and command channel |
| SNS | Event bus for inbound WhatsApp messages |
| Lambda (Dispatcher) | Routes WhatsApp events to Bedrock Agent or Store API |
| Lambda (Store API) | Flask REST API for orders, products, reviews, escalations |
| Bedrock Agents (Nova Lite) | Real-time customer WhatsApp chat |
| EKS | Hosts OpenClaw gateway (Claude) for the seller Telegram channel |
| RDS MySQL | Products, customers, orders, reviews, escalations |
| SES | Order confirmation, shipping, and refund emails |
| CloudFront + S3 | Static web storefront and admin dashboard |
| API Gateway | REST endpoint for the Store API |
| NLB | Exposes OpenClaw on EKS to the Dispatcher Lambda |
| Secrets Manager | Database credentials |

---

## Demo walkthrough

A single order touches the web storefront, WhatsApp, email, Telegram, and the admin dashboard. Here is the full flow.

### Step 1: Place an order

Open the storefront, add an item to cart, fill in your name, email, and phone number, and click Place Order.

![Storefront](docs/screenshot-storefront.png)

![Checkout](docs/screenshot-checkout.png)

### Step 2: Receive order confirmation

Two things happen immediately:

- **WhatsApp** -- The customer gets a confirmation message with the order number, items, and total, followed by a feedback survey ("rate 1-5").
- **Email** -- A confirmation email arrives via SES with the same order details.

<img src="docs/mockup-email-confirmation.png" width="560" alt="Order confirmation email">

<img src="docs/mockup-wa-survey.png" width="380" alt="WhatsApp confirmation and survey">

### Step 3: Low stock alert on Telegram

Every purchase triggers a stock check. If any item drops below threshold (out of stock, fewer than 5 units, or projected to run out within 7 days), the seller gets a Telegram alert with stock levels and sell rates.

The seller can reply `restock <product>` to add inventory. ClawBot runs the restock tool and confirms the new total.

<img src="docs/mockup-tg-stock.png" width="380" alt="Telegram stock alert">

### Step 4: Customer gives negative feedback

The customer replies "1" to the WhatsApp survey. The Store API creates an escalation record and sends the seller a Telegram review alert with the customer's name, phone, rating, and review text.

<img src="docs/mockup-tg-escalation.png" width="380" alt="Telegram review escalation">

### Step 5: Seller sends refund via Telegram

The seller replies `apologize` on Telegram. ClawBot looks up the unresolved escalation, then:

1. Sends a WhatsApp apology message to the customer
2. Sends a refund confirmation email to the customer via SES
3. Marks the order as "refunded" in the database
4. Resolves the escalation

If there are multiple open escalations, ClawBot lists them and asks which one.

### Step 6: Check the admin dashboard

The seller opens the admin dashboard to see orders (now showing "refunded" status), escalation history, stock levels, and products.

![Admin Dashboard](docs/screenshot-admin-dashboard.png)

![Admin Orders](docs/screenshot-admin-orders.png)

---

## Other features

**Order via WhatsApp** -- Customers can browse and order by texting the WhatsApp business number directly. The Bedrock Agent handles the full conversation.

<img src="docs/mockup-wa-order.png" width="380" alt="WhatsApp order conversation">

**Telegram seller commands** -- The store owner can manage the shop entirely from Telegram:

| Command | What it does |
|---------|-------------|
| `restock <product>` | Add 1 unit to inventory (or specify qty) |
| `apologize` | Send WhatsApp apology + refund email, resolve escalation |
| `confirm <order>` | Confirm a pending order |
| `cancel <order>` | Cancel an order |
| `ship <order>` | Mark order as shipped |
| `stock report` | Get current inventory levels |
| `orders` | List recent or pending orders |

**AI Insights** -- OpenClaw generates periodic business insights based on order patterns and customer feedback, visible on the admin dashboard.

![AI Insights](docs/screenshot-admin-insights.png)

---

## Project structure

```
claw-boutique/
  cdk/                    CDK stack (EKS, RDS, VPC, Lambda, SNS, SES, S3, CloudFront)
  docker/openclaw/        Dockerfile for OpenClaw container (built by CDK, pushed to ECR)
  lambda/
    dispatcher/           SNS event router (TypeScript)
    store-api/            Flask REST API (Python)
    db-initializer/       Custom resource Lambda for schema + seed data
  openclaw/
    openclaw.json         Agent config (model, tools, channels)
    tools/                Python tool scripts called by OpenClaw (restock, apologize, etc.)
  web/static/
    index.html            Storefront
    admin.html            Admin dashboard
    js/store.js           Storefront logic
    js/admin.js           Admin dashboard logic
  docs/                   Architecture diagram, mockups, screenshots
```

---

## Deployment

CDK deploys all AWS resources in one command, including the EKS cluster, RDS database, and OpenClaw container.

```bash
git clone <this-repo>
cd claw-boutique

# Copy the context template and fill in your values
cp cdk/cdk.context.example.json cdk/cdk.context.json
# Edit cdk/cdk.context.json with your Telegram bot token, seller chat ID,
# WhatsApp phone number ID, WABA ID, and SES sender email

cd cdk && npm install
npx cdk bootstrap
npx cdk deploy
```

CDK reads credentials from `cdk/cdk.context.json` (gitignored). You can also pass them as CLI flags:

```bash
npx cdk deploy \
  -c telegramBotToken="<token>" \
  -c telegramSellerId="<id>" \
  -c whatsappPhoneNumberId="<id>" \
  -c whatsappWabaId="<id>" \
  -c sesFromEmail="you@example.com"
```

CDK handles database initialization (schema + seed data), Docker image build, ECR push, and EKS deployment automatically.

After CDK finishes:

1. **WhatsApp** -- CDK automatically links your WABA to the SNS topic. No manual step needed.
2. **Telegram (one-time)** -- Send `/start` to the bot from the seller's Telegram account.
3. **SES (one-time)** -- Verify your sender email address or domain in the SES console.

Steps 2 and 3 only need to be done once per account. Subsequent deploys reuse existing config.

### Connecting to OpenClaw on EKS

After deploy, CDK prints a `ClawBoutiqueClusterConfigCommand` output with the exact command. Copy and run it:

```bash
# Printed in CDK outputs -- copy the exact command from your deploy
aws eks update-kubeconfig --name claw-boutique --region us-east-1 --role-arn arn:aws:iam::<account>:role/Admin
```

Then:

```bash
kubectl get pods -n default -l app=openclaw       # Check pod status
kubectl logs -n default -l app=openclaw --tail=50  # View logs
kubectl port-forward svc/openclaw 18789:80         # Local access at localhost:18789
```

With the port-forward running, open `http://localhost:18789` to access the OpenClaw Control UI. The UI requires a gateway token for authentication. Get it from the running pod:

```bash
kubectl exec deploy/openclaw -c openclaw -- printenv OPENCLAW_GATEWAY_TOKEN
```

Paste the token into the Control UI settings (gear icon, top right). The token regenerates on every `cdk deploy`, so you will need to grab it again after redeployments.

---

## License

MIT
