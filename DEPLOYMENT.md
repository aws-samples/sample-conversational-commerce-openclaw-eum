# ClawBot Deployment Guide

This guide walks you through deploying the complete end-to-end system in ~30 minutes.

## Prerequisites

Before you start, ensure you have:

1. **AWS Account** with permissions for: CDK, SNS, Lambda, SES, Secrets Manager, CloudWatch
2. **Meta WhatsApp Business Account** with system user token (for End User Messaging Social)
3. **Lightsail instance running OpenClaw** (blueprint deployed, minimum 4GB RAM)
4. **Local tools**: AWS CLI, Node.js 18+, Python 3.8+, MySQL CLI, CDK

## Quick Deploy (3 steps)

```bash
# 1. Clone and setup
git clone <this-repo>
cd claw-boutique
cp .env.example .env

# 2. Configure environment
source scripts/setup-env.sh
# Edit .env with your values:
vim .env
bash scripts/validate-env.sh

# 3. Deploy everything
bash scripts/deploy.sh \
  --region ap-southeast-1 \
  --stack-name ClawBoutiqueStack \
  --openclw-instance-ip 1.2.3.4 \
  --openclw-instance-user ec2-user
```

That's it! The script handles:
- CDK stack deployment (SNS, Lambda, SES, IAM)
- Lambda build & packaging
- Database creation & seeding
- OpenClaw configuration
- End User Messaging Social validation

## Step-by-Step Breakdown

### Step 1: Environment Setup

```bash
# Copy template
cp .env.example .env

# Fill in your values
vim .env
```

**Required variables:**
- `AWS_REGION` — your AWS region
- `LIGHTSAIL_INSTANCE_IP` — public IP of your OpenClaw Lightsail instance
- `DB_HOST` — Lightsail MySQL endpoint or RDS instance
- `DB_PASSWORD` — secure database password
- `WHATSAPP_PHONE_NUMBER_ID` — from Meta Business Manager
- `WHATSAPP_TOKEN` — system user token from Meta
- `SELLER_PHONE` — seller's phone in E.164 format (e.g., `+1-212-555-0101`)
- `SES_FROM_EMAIL` — verified SES sender email

### Step 2: Validate Environment

```bash
# Bootstrap setup
source scripts/setup-env.sh

# Deep validation
bash scripts/validate-env.sh
```

This confirms all credentials work before deployment.

### Step 3: Deploy Infrastructure

```bash
bash scripts/deploy.sh \
  --region ap-southeast-1 \
  --stack-name ClawBoutiqueStack \
  --openclw-instance-ip 1.2.3.4 \
  --openclw-instance-user ec2-user
```

The script will:
1. Build CDK stack and deploy via CloudFormation
2. Create Secrets Manager secret for DB credentials
3. Create MySQL database and seed with products
4. Build Lambda Dispatcher and output deployment instructions
5. Copy OpenClaw config to Lightsail instance
6. Validate SNS topic is ready for End User Messaging Social
7. Print final summary with all endpoints

### Step 4: Post-Deployment Manual Steps

After the script completes:

1. **Deploy Lambda Dispatcher** (output will show exact CLI command):
   ```bash
   aws lambda update-function-code \
     --function-name ClawBoutiqueDispatcher \
     --zip-file fileb://lambda/dispatcher/claw-boutique-dispatcher.zip
   ```

2. **Link WhatsApp Business Number to SNS Topic** (via AWS console):
   - Go to End User Messaging Social → Business Accounts
   - Select your WABA
   - Event Destinations: enter SNS topic ARN (from deployment output)

3. **Start OpenClaw** on Lightsail:
   ```bash
   ssh -i ~/.ssh/lightsail.pem ec2-user@1.2.3.4
   openclaw start --config ~/.openclaw/openclaw.json --env-file ~/.env
   ```

### Step 5: Validate Deployment

```bash
bash scripts/validate-setup.sh
```

This checks all components are operational:
- ✓ SNS topic exists and has correct policy
- ✓ Lambda function is Active and subscribed to SNS
- ✓ Database has all tables and is seeded
- ✓ OpenClaw gateway is reachable on port 8443
- ✓ SES domain is verified
- ✓ CloudWatch logs exist

## End-to-End Demo

Once deployed, run the interactive demo:

```bash
bash scripts/demo.sh
```

This walks through:
1. **Show products** — queries catalog
2. **Customer orders** — publishes demo WhatsApp order via SNS
3. **Check database** — verifies order was created
4. **Validate email** — checks order confirmation template
5. **Seller queries** — simulates seller asking "What orders today?"
6. **Fulfill order** — marks order as shipped, updates customer
7. **Summary** — all green checkmarks

## Health Checks

```bash
# Quick system status
bash scripts/health-check.sh

# Demo flow (interactive)
bash scripts/demo.sh

# Test Lambda with sample event
aws lambda invoke \
  --function-name ClawBoutiqueDispatcher \
  --cli-binary-format raw-in-base64-out \
  --payload file://scripts/test-flow.json \
  /tmp/response.json
cat /tmp/response.json
```

## Troubleshooting

### "SNS topic not found"
- Check `AWS_REGION` matches your deployment region
- Verify CDK deploy succeeded: `aws cloudformation list-stacks`

### "Lambda cannot reach OpenClaw"
- Check `OPENCLAW_GATEWAY_URL` is correct and reachable
- Verify Lightsail security group allows inbound on port 8443
- Check OpenClaw is running: `ssh ... curl https://localhost:8443/health`

### "Database connection failed"
- Verify `DB_HOST` is reachable from Lambda: `mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD`
- Check security group allows inbound on port 3306 from Lambda security group

### "WhatsApp messages not arriving"
- Verify `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_TOKEN` are correct
- Check SNS topic has `social-messaging.amazonaws.com` publish permission
- Verify Lambda has `social-messaging:SendWhatsAppMessage` IAM permission

### "SES emails not sending"
- Verify `SES_FROM_EMAIL` is verified in SES console
- Check SES is not in sandbox mode (production access required)
- Verify Lambda has `ses:SendEmail` permission

## What Happens After Deployment

1. **Customer sends WhatsApp message** to your business number
   → End User Messaging Social receives it
   → Publishes to SNS topic
   → Lambda Dispatcher processes it
   → Forwards to OpenClaw gateway
   → OpenClaw calls database tools, SES, WhatsApp reply APIs
   → Customer gets confirmation on WhatsApp
   → Seller gets an alert on personal WhatsApp

2. **Seller asks OpenClaw** questions via personal WhatsApp
   → OpenClaw reads from database
   → Responds with order status, inventory, etc.

3. **Customer emails support** → SES receipt rule catches it
   → Routes to SNS topic
   → Lambda Dispatcher routes to OpenClaw
   → OpenClaw triages: auto-reply if simple, escalate if complex

## Next Steps

After successful deployment:

1. **Test with real WhatsApp** — send your first order through the business number
2. **Monitor CloudWatch logs** — check `/aws/lambda/ClawBoutiqueDispatcher` for any errors
3. **Scale up** — add SMS channel (End User Messaging SMS), voice support, fulfillment webhooks
4. **Integrate fulfillment** — connect to shipping partners via SNS fan-out

## Cost

Estimated monthly costs for the demo:
- **Lightsail** (4GB): $20
- **Lambda**: < $1 (free tier covers it)
- **SNS**: < $1
- **SES**: ~$0.10 per 1,000 emails
- **Bedrock/Claude**: ~$0.03 per 1,000 requests (60 requests/day = ~$1.80)
- **RDS/MySQL**: $10-20 (if using RDS instead of Lightsail managed DB)

**Total: ~$35-40/month** at low volume.

## Support

For issues:
1. Check CloudWatch logs: `aws logs tail /aws/lambda/ClawBoutiqueDispatcher --follow`
2. Run health check: `bash scripts/health-check.sh`
3. Check system configuration: `bash scripts/validate-env.sh`
