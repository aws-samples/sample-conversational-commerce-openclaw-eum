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
    send_email.py
    update_order_status.py
```

---

## 1. Deploy on Lightsail

### One-time blueprint setup

1. Create a Lightsail instance using the **OS Only > Amazon Linux 2023** blueprint (minimum 2 GB RAM recommended).
2. Open ports **8443** (HTTPS/OpenClaw gateway) and **22** (SSH) in the Lightsail firewall under **Networking > IPv4 firewall**.
3. SSH into the instance:
   ```
   ssh -i ~/.ssh/your-key.pem ec2-user@<instance-ip>
   ```
4. Install Docker:
   ```
   sudo yum update -y
   sudo yum install -y docker
   sudo systemctl enable --now docker
   sudo usermod -aG docker ec2-user
   ```
   Log out and back in so the group change takes effect.
5. Install OpenClaw (follow the official OpenClaw install docs or your internal package step).
6. Copy this entire `openclaw/` directory to the instance:
   ```
   scp -i ~/.ssh/your-key.pem -r ./openclaw ec2-user@<instance-ip>:/opt/claw-boutique/openclaw
   ```
7. Build the tools Docker image:
   ```
   cd /opt/claw-boutique/openclaw/tools
   docker build -t claw-boutique/openclaw-tools:latest .
   ```
8. Populate the environment file (see Section 3 below), then start the gateway:
   ```
   openclaw start --config /opt/claw-boutique/openclaw/openclaw.json
   ```
9. Point your WhatsApp webhook and SES inbound rule at `https://<instance-ip>:8443/webhook/whatsapp` and `https://<instance-ip>:8443/webhook/seller`.

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
| `DB_HOST` | MySQL/MariaDB host | `db.internal` or `127.0.0.1` |
| `DB_USER` | Database user | `clawbot` |
| `DB_PASSWORD` | Database password | (from secrets manager) |
| `DB_NAME` | Database name | `claw_boutique` |

### Setting variables on Lightsail

Create `/opt/claw-boutique/.env` (readable only by the service user):

```
DB_HOST=your-rds-or-lightsail-db-host
DB_USER=clawbot
DB_PASSWORD=supersecretpassword
DB_NAME=claw_boutique

WHATSAPP_API_URL=https://graph.facebook.com/v19.0
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_TOKEN=your_system_user_token
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your_webhook_verify_token

AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=ap-southeast-1
SES_FROM_EMAIL=orders@clawboutique.ph
SES_FROM_NAME=Claw Boutique

SELLER_PHONE=+639171234567
SELLER_EMAIL=owner@clawboutique.ph
SELLER_NAME=Ate Claire

OPENCLAW_GATEWAY_TOKEN=your_daily_rotated_token
REDIS_HOST=127.0.0.1
REDIS_PASSWORD=
```

Restrict permissions:
```
chmod 600 /opt/claw-boutique/.env
```

Start the gateway with the env file:
```
openclaw start --config /opt/claw-boutique/openclaw/openclaw.json --env-file /opt/claw-boutique/.env
```

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
export WHATSAPP_API_URL=https://graph.facebook.com/v19.0
export WHATSAPP_PHONE_NUMBER_ID=1234567890
export WHATSAPP_TOKEN=your_token

python tools/send_customer_reply.py \
  --customer_phone "+639171234567" \
  --message_type text \
  --message_content "$(echo -n 'Hi! Your order is confirmed.' | base64)"
```

### send_email (requires AWS env vars)
```bash
export AWS_ACCESS_KEY_ID=AKIAxxxxxxxx
export AWS_SECRET_ACCESS_KEY=xxxxxxxx
export AWS_REGION=ap-southeast-1
export SES_FROM_EMAIL=orders@clawboutique.ph
export SES_FROM_NAME="Claw Boutique"

python tools/send_email.py \
  --recipient_email "jane@example.com" \
  --template_name order_confirmation \
  --variables '{"customer_name":"Jane","order_id":"ORD-001","items_summary":"1x Black Crop Top (M)","total":"499.00","shop_url":"https://clawboutique.ph"}'
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

The system prompt drives ClawBot's personality, rules, and capabilities. It lives in `system-prompt.md` and is loaded at gateway startup.

To update it:

1. Edit `system-prompt.md` with your changes.
2. Reload the OpenClaw config without a full restart:
   ```
   openclaw reload --config /opt/claw-boutique/openclaw/openclaw.json
   ```
   Or, if hot-reload is not available, do a graceful restart:
   ```
   openclaw stop --config /opt/claw-boutique/openclaw/openclaw.json
   openclaw start --config /opt/claw-boutique/openclaw/openclaw.json --env-file /opt/claw-boutique/.env
   ```
3. Active conversations pick up the new prompt on the next message. In-flight tool calls use the prompt that was active when the conversation started.

**Tip:** Keep a changelog comment at the top of `system-prompt.md` when making significant rule changes, so the history is traceable without needing git blame.

---

## 6. Token Rotation

The gateway token (`OPENCLAW_GATEWAY_TOKEN`) rotates daily. Update the env file and reload:

```bash
# Generate a new token
NEW_TOKEN=$(openssl rand -hex 32)

# Update the env file
sed -i "s/^OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=$NEW_TOKEN/" /opt/claw-boutique/.env

# Reload the gateway (picks up new env var)
openclaw reload --config /opt/claw-boutique/openclaw/openclaw.json
```

Automate this with a cron job running at midnight:

```
0 0 * * * /opt/claw-boutique/scripts/rotate_token.sh >> /var/log/openclaw_token_rotation.log 2>&1
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Tool returns `{"error": "Missing required environment variable: DB_HOST"}` | Verify the `.env` file is loaded and the variable is set |
| WhatsApp messages not sending | Check `WHATSAPP_TOKEN` expiry; verify `WHATSAPP_PHONE_NUMBER_ID` is correct |
| Emails not arriving | Check SES sandbox mode; verify `SES_FROM_EMAIL` is a verified identity |
| Gateway returns 401 | `OPENCLAW_GATEWAY_TOKEN` may have rotated; update the calling service |
| Seller commands not recognised | Verify `SELLER_PHONE` in env matches the E.164 number the seller is sending from |
| Docker sandbox timeout | Increase `execution_timeout_seconds` in `openclaw.json`; check DB connectivity from within the container |
