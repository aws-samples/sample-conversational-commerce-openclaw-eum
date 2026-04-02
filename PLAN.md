# Claw Boutique — Project Plan

## What's Been Built

### Core Architecture
- CDK stack (`ClawBoutiqueStack`) deploying full AWS infrastructure
- Two-channel AI design: Bedrock Agent (Nova Lite) for customer WhatsApp, OpenClaw (Claude Sonnet on Lightsail) for seller Telegram
- Store API Lambda (Flask/Mangum) backed by MySQL on RDS
- CloudFront + S3 web storefront and admin dashboard
- SNS-based event routing via Dispatcher Lambda

### Customer Channel (WhatsApp → Bedrock Agent)
- EUMS Social receives WhatsApp messages → SNS → Dispatcher → Bedrock Agent
- Agent has read-only tools: `list_products`, `get_product`, `get_order`, `create_escalation`
- Customers cannot place orders via WhatsApp — directed to web storefront
- Survey rating replies (1-5) handled before Bedrock to submit reviews

### Seller Channel (Telegram → OpenClaw)
- Switched from WhatsApp to Telegram (agent-bridge on Lightsail port 18790)
- OpenClaw receives commands via Telegram bot, executes Python tools in Docker containers
- Tools: `escalate_to_human`, `send_email`, `create_order`, `restock_product`, `analyze_stock`, `handle_review`, `save_memory`, `recall_memory`, `recover_cart`, `update_order_status`, `send_customer_reply`
- Memory system: OpenClaw saves/recalls interaction patterns to reduce future escalations

### Notifications
- Stock alerts and review alerts → seller Telegram via agent-bridge (`_notify_seller`)
- Order confirmation email → customer via SES on web checkout (`_send_order_confirmation_email`)
- Shipped order email → customer via OpenClaw `send_email` tool (seller-triggered)
- Escalation alerts → seller Telegram only (email escalation removed)

### Security (recent additions — not yet deployed via CDK)
- Bedrock Guardrail (`ClawBoutiqueGuardrail`) — denied topic for prompt injection
- Guardrail associated with Bedrock Agent
- Dispatcher wraps customer input: `[Customer WhatsApp message from +X]\n<text>`
- OpenClaw system prompt: explicit channel trust rule (Telegram = trusted, all else = untrusted data)

---

## Uncommitted Changes (current session)

These are modified but not yet committed or fully deployed:

| File | Change |
|---|---|
| `cdk/lib/claw-boutique-stack.ts` | Bedrock Guardrail resource, guardrail on agent, SES IAM + env vars for Store API, hardened agent instruction |
| `lambda/dispatcher/index.ts` | Customer input wrapping for prompt injection defence |
| `lambda/store-api/server.py` | `_send_order_confirmation_email()` helper, called in `create_order()` |
| `openclaw/openclaw.json` | Removed `escalation_alert` from `send_email` tool, added bridge env vars to sandbox |
| `openclaw/system-prompt.md` | Channel trust constraint (Telegram trusted, customer data untrusted) |
| `openclaw/tools/escalate_to_human.py` | Removed `_send_escalation_email()` and optional email path entirely |
| `openclaw/tools/send_email.py` | Removed `escalation_alert` template |

**Deployed directly (bypassing CDK):**
- Store API Lambda: new code + `SES_FROM_EMAIL=rsunga.aws@gmail.com`, `SES_FROM_NAME=Claw Boutique`
- Store API IAM role: `SendOrderEmails` inline policy (`ses:SendEmail`, `ses:SendRawEmail`)

**Not yet deployed:**
- CDK changes (Guardrail, hardened agent instruction, dispatcher input wrapping) — needs `cdk deploy`
- OpenClaw tools on Lightsail — need to be synced after `escalate_to_human.py` and `send_email.py` changes
- Dispatcher Lambda — needs rebuild and deploy after `index.ts` change

---

## Pending / Known Gaps

### Must-do before demo
- [ ] Commit all uncommitted changes
- [ ] `cdk deploy` to apply Guardrail + hardened agent instruction
- [ ] Rebuild and deploy Dispatcher Lambda (`cd lambda/dispatcher && npm run build && zip...`)
- [ ] Sync updated OpenClaw tools to Lightsail (`escalate_to_human.py`, `send_email.py`)

### Should-do
- [ ] SES sandbox: `rsunga.aws@gmail.com` is the only verified sender — order confirmation emails only reach verified recipient addresses. Request SES production access to send to any address.
- [ ] SHOP_URL env var for Store API Lambda — currently hardcoded fallback to CloudFront URL in `_send_order_confirmation_email()`
- [ ] CDK should manage the `SendOrderEmails` IAM policy and SES env vars (currently set directly via CLI)
- [ ] E2E tests after deploying guardrail — confirm Bedrock Agent still responds correctly with guardrail active

### Nice-to-have / Future
- [ ] Bedrock Guardrail version pinning — currently uses `DRAFT`; should publish a version and pin alias to it
- [ ] OpenClaw on ECS/Fargate with IAM roles instead of static credentials on Lightsail (production hardening)
- [ ] VPC placement for Lightsail → RDS path
- [ ] SES production access request
- [ ] CloudWatch alarms on Dispatcher and Store API error rates
- [ ] Cost tracking: Nova Lite per-message cost vs. Claude Sonnet seller channel

---

## Live Resources

| Resource | Value |
|---|---|
| Storefront | https://d22y1hcx8ni0pf.cloudfront.net |
| Store API | https://h08zylpngj.execute-api.us-east-1.amazonaws.com/prod/ |
| Lightsail IP | 32.195.52.35 |
| AWS Region | us-east-1 |
| AWS Profile | claude-code |
| CDK Stack | `ClawBoutiqueStack` |
| SES verified sender | `rsunga.aws@gmail.com` |
