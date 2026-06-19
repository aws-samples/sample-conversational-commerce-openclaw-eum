# OpenClaw — Claw Boutique Quick Reference

This directory contains the OpenClaw AI gateway configuration for Claw Boutique. ClawBot handles customer orders on WhatsApp, email support triage, and seller commands.

---

## Directory Layout

```
openclaw/
  openclaw.json      # Main OpenClaw configuration
  system-prompt.md   # ClawBot personality, rules, and instructions
  tools/             # Python tool scripts (run inside Docker sandbox)
    create_order.py
    escalate_to_human.py
    list_products.py
    lookup_order.py
    send_customer_reply.py
    update_order_status.py
```

---

## 1. Deploy on EKS

OpenClaw runs as a Docker container on EKS. CDK handles the full deployment automatically, including building the image, pushing it to ECR, and creating the Kubernetes Deployment, Service, and ConfigMap.

### What CDK does

- Builds the Docker image from `docker/openclaw/Dockerfile`.
- Pushes the image to ECR.
- Creates a Kubernetes ConfigMap from `openclaw/openclaw.json`.
- Injects all required environment variables into the Deployment (DB credentials, Telegram token, WhatsApp IDs, etc.).
- Exposes the gateway via a Kubernetes LoadBalancer Service on port 18789.

### Deploy

```bash
npx cdk deploy --profile claude-code \
  -c telegramBotToken="<token>" \
  -c telegramSellerId="<id>" \
  -c whatsappPhoneNumberId="<id>" \
  -c whatsappWabaId="<id>"
```

CDK connects to the `claw-boutique` EKS cluster and applies all Kubernetes manifests. No manual SSH, no firewall rules, no instance setup.

### Verify the pod is running

```bash
kubectl get pods -n openclaw
kubectl logs -n openclaw -l app=openclaw --tail=50
```

---

## 2. Connect the Seller's Telegram Bot

OpenClaw connects to the seller via a Telegram bot. This allows the seller to receive alerts and send operational commands directly from Telegram.

1. Create a bot via BotFather and note the token.
2. Add the Telegram channel to OpenClaw:
   ```
   openclaw channels add --channel telegram --token "<bot-token>"
   openclaw config set channels.telegram.dmPolicy open
   openclaw config set channels.telegram.allowFrom '["*"]' --strict-json
   ```
3. The seller must send `/start` to the bot before messages can be delivered.
4. Verify the channel is running:
   ```
   openclaw channels status
   ```

**Note:** The Telegram bot channel is separate from the WhatsApp Business API (WABA) used for customer messages. Customer WhatsApp messages go through EUMS/SNS to the Bedrock Agent.

---

## 3. Configure the Database Connection

All tool scripts read database credentials from environment variables. Never hardcode credentials in `openclaw.json` or any script.

### Required variables

| Variable | Description | Example |
|---|---|---|
| `DB_HOST` | RDS endpoint | `clawboutiquestack-....rds.amazonaws.com` |
| `DB_USER` | Database user | `clawbot` |
| `DB_PASSWORD` | Database password | (from Secrets Manager) |
| `DB_NAME` | Database name | `claw_boutique` |

### How variables are injected

CDK reads the RDS endpoint and credentials from the stack and injects them directly into the EKS Deployment as environment variables. You do not manage a `.env` file on a server.

The full set of variables CDK injects:

```
DB_HOST              # RDS endpoint (set automatically from stack outputs)
DB_USER              # from Secrets Manager
DB_PASSWORD          # from Secrets Manager
DB_NAME=claw_boutique

WHATSAPP_PHONE_NUMBER_ID   # from CDK context
AWS_REGION=us-east-1
SES_FROM_EMAIL=orders@clawboutique.ph
SES_FROM_NAME=Claw Boutique

SELLER_NAME=Ate Claire
TELEGRAM_BOT_TOKEN         # from CDK context
TELEGRAM_SELLER_ID         # from CDK context

OPENCLAW_GATEWAY_TOKEN     # generated and stored in Secrets Manager
REDIS_HOST                 # set automatically from stack outputs
REDIS_PASSWORD             # from Secrets Manager
```

To change a value, update the CDK stack or context parameter and redeploy. The pod restarts automatically with the new values.

---

## 4. Test Tools Locally

You can invoke any tool script directly from the command line without running the full gateway. This is useful for checking DB connectivity and validating tool output before deployment.

Make sure the required environment variables are exported first (or use a `.env` loader like `dotenv`):

```bash
export DB_HOST=localhost
export DB_USER=clawbot
export DB_PASSWORD=yourpassword
export DB_NAME=claw_boutique
```

### lookup_order
```bash
python tools/lookup_order.py --order_id "some-uuid-here"
```

### list_products
```bash
python tools/list_products.py --category tops --size M --color black
python tools/list_products.py   # returns all products
```

### create_order
```bash
python tools/create_order.py \
  --customer_phone "+639171234567" \
  --customer_name "Jane Reyes" \
  --customer_email "jane@example.com" \
  --items '[{"product_id": "prod-uuid-here", "qty": 2}]'
```

### update_order_status
```bash
python tools/update_order_status.py \
  --order_id "order-uuid-here" \
  --new_status shipped \
  --tracking_url "https://track.jnt.express/12345"
```

### send_customer_reply (requires WhatsApp env vars)
```bash
export WHATSAPP_PHONE_NUMBER_ID=1234567890

python tools/send_customer_reply.py \
  --customer_phone "+639171234567" \
  --message_type text \
  --message_content "$(echo -n 'Hi! Your order is confirmed.' | base64)"
```

### escalate_to_human (requires DB + agent-bridge env vars)
```bash
python tools/escalate_to_human.py \
  --reason "Refund request" \
  --customer_phone "+639171234567" \
  --summary "Customer says she received the wrong size. Ordered M, received L."
```

All tools output a JSON object to stdout. An `{"error": "..."}` key indicates failure.

---

## 5. Update the System Prompt

The system prompt drives ClawBot's personality, rules, and capabilities. It lives in `system-prompt.md` and is loaded at gateway startup via the Kubernetes ConfigMap.

To update it:

1. Edit `system-prompt.md` with your changes.
2. Redeploy with CDK (or just re-apply the ConfigMap and restart the pod):
   ```bash
   # Option A: full CDK redeploy (also picks up any other changes)
   npx cdk deploy --profile claude-code -c ...

   # Option B: restart the pod to pick up a ConfigMap-only change
   kubectl rollout restart deployment/openclaw -n openclaw
   ```
3. Active conversations pick up the new prompt on the next message. In-flight tool calls use the prompt that was active when the conversation started.

**Tip:** Keep a changelog comment at the top of `system-prompt.md` when making significant rule changes, so the history is traceable without needing git blame.

---

## 6. Token Rotation

The gateway token (`OPENCLAW_GATEWAY_TOKEN`) rotates daily. It is stored in AWS Secrets Manager. A scheduled Lambda (or EventBridge rule) generates a new token, updates the secret, and triggers a rolling restart of the pod:

```bash
kubectl rollout restart deployment/openclaw -n openclaw
```

The pod pulls the new token from Secrets Manager at startup. No manual file editing required.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Tool returns `{"error": "Missing required environment variable: DB_HOST"}` | Run `kubectl describe pod -n openclaw <pod>` and verify the env vars are present; check CDK deployed with the correct context values |
| Pod stuck in `CrashLoopBackOff` | `kubectl logs -n openclaw <pod> --previous` to see the last crash output |
| WhatsApp messages not sending | Verify `WHATSAPP_PHONE_NUMBER_ID` is correct and EUMS is configured |
| Emails not arriving | Check SES sandbox mode; verify `SES_FROM_EMAIL` is a verified identity |
| Gateway returns 401 | `OPENCLAW_GATEWAY_TOKEN` may have rotated; update the calling service or restart the pod to pull the latest secret |
| Seller commands not recognised | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_SELLER_ID` are set in the Deployment; check `kubectl logs -n openclaw -l app=openclaw` |
| Cannot reach RDS | `DB_HOST` must be the RDS endpoint (not `localhost`); verify the EKS node security group allows outbound to the RDS security group on port 3306 |
| Docker sandbox timeout | Increase `execution_timeout_seconds` in `openclaw.json`; check DB connectivity from within the container |
