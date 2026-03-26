/**
 * ClawBoutiqueStack
 *
 * Infrastructure for the Claw Boutique messaging and backend system.
 *
 * Architecture overview
 * ---------------------
 *  1. SNS Topic "ClawBoutiqueInbound"
 *       ↑  End User Messaging Social (WhatsApp) publishes inbound messages here
 *          via the topic's resource policy (social-messaging.amazonaws.com).
 *       Subscriber → Lambda Dispatcher
 *
 *  2. Lambda Dispatcher
 *       - Receives SNS events (WhatsApp inbound messages, SES inbound notifications)
 *       - Can reply via social-messaging:SendWhatsAppMessage
 *       - Can send email via ses:SendEmail / ses:SendRawEmail
 *       - Code asset lives in ../lambda/dispatcher (built separately)
 *
 *  3. SES domain identity + receipt rule set
 *       - Domain: clawboutique.example.com
 *       - Inbound receipt rule for support@clawboutique.com → SNS action
 *         (publishes raw email to ClawBoutiqueInbound, picked up by dispatcher)
 *
 *  4. Lightsail IAM role
 *       - Assumed by the OpenClaw app running on Lightsail
 *       - Grants read access to the DB credentials secret only
 *
 *  5. Secrets Manager secret "ClawBoutique/DbCredentials"
 *       - Stores RDS/MySQL DB host, port, name, username, password
 *       - Placeholder values — replace via AWS Console or CLI before first deploy
 */

import {
  Stack,
  StackProps,
  CfnOutput,
  Duration,
  RemovalPolicy,
  SecretValue,
} from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as ses from "aws-cdk-lib/aws-ses";
import * as sesActions from "aws-cdk-lib/aws-ses-actions";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as logs from "aws-cdk-lib/aws-logs";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as bedrock from "aws-cdk-lib/aws-bedrock";

// ---------------------------------------------------------------------------
// Constants — update these before deploying to production
// ---------------------------------------------------------------------------
// Read domain config from environment or context; fall back to example values.
const DOMAIN = process.env.SES_DOMAIN || "clawboutique.example.com";
const SUPPORT_EMAIL = process.env.SES_SUPPORT_EMAIL || `support@${DOMAIN}`;
// The Lightsail instance principal that may assume the OpenClaw role.
// Set LIGHTSAIL_PRINCIPAL to the Lightsail instance IAM ARN to scope down.
// Falls back to the deploying account root (same-account assumption only).
const LIGHTSAIL_ACCOUNT_PRINCIPAL = process.env.LIGHTSAIL_PRINCIPAL || "";

export class ClawBoutiqueStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // =========================================================================
    // 1. KMS key — used to encrypt the SNS topic so that the End User Messaging
    //    Social service principal can encrypt/decrypt messages at rest.
    // =========================================================================
    const topicKey = new kms.Key(this, "ClawBoutiqueTopicKey", {
      description:
        "CMK for ClawBoutiqueInbound SNS topic. " +
        "Grants social-messaging and ses service principals decrypt access.",
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Allow the service principals that publish to the topic to use this key.
    topicKey.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowEUMAndSESKmsAccess",
        effect: iam.Effect.ALLOW,
        principals: [
          new iam.ServicePrincipal("social-messaging.amazonaws.com"),
          new iam.ServicePrincipal("ses.amazonaws.com"),
        ],
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: ["*"],
      })
    );

    // =========================================================================
    // 2. SNS Topic — "ClawBoutiqueInbound"
    //
    //    End User Messaging Social Integration point:
    //    In the AWS End User Messaging Social console, when you register your
    //    WhatsApp Business Account phone number you configure an "event
    //    destination". Set that destination to this topic ARN (exported below
    //    as ClawBoutiqueInboundTopicArn). The resource policy below grants the
    //    social-messaging.amazonaws.com service principal permission to publish.
    // =========================================================================
    const inboundTopic = new sns.Topic(this, "ClawBoutiqueInbound", {
      topicName: "ClawBoutiqueInbound",
      displayName: "Claw Boutique — Inbound Messages (WhatsApp + Email)",
      masterKey: topicKey,
    });

    // Grant End User Messaging Social (WhatsApp) publish rights.
    // This policy statement is what the EUM Social service checks before
    // delivering a webhook event from your registered phone number to SNS.
    inboundTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowEUMSocialPublish",
        effect: iam.Effect.ALLOW,
        principals: [
          new iam.ServicePrincipal("social-messaging.amazonaws.com"),
        ],
        actions: ["sns:Publish"],
        resources: [inboundTopic.topicArn],
        // Scope the permission to events originating from this AWS account only,
        // preventing cross-account abuse.
        conditions: {
          StringEquals: {
            "AWS:SourceAccount": this.account,
          },
        },
      })
    );

    // Grant SES permission to publish inbound email receipt notifications.
    inboundTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowSESReceiptPublish",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("ses.amazonaws.com")],
        actions: ["sns:Publish"],
        resources: [inboundTopic.topicArn],
        conditions: {
          StringEquals: {
            "AWS:SourceAccount": this.account,
          },
        },
      })
    );

    // =========================================================================
    // 3. Lambda Dispatcher — IAM execution role
    //
    //    Permissions granted:
    //      • SNS read (DescribeTopic, GetTopicAttributes) — subscribe/inspect
    //      • social-messaging:SendWhatsAppMessage — reply via EUM Social
    //      • ses:SendEmail + ses:SendRawEmail — send outbound support emails
    //      • logs:CreateLogGroup/Stream/PutLogEvents — CloudWatch logging
    // =========================================================================
    const dispatcherRole = new iam.Role(this, "DispatcherLambdaRole", {
      roleName: "ClawBoutiqueDispatcherLambdaRole",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description:
        "Execution role for the Claw Boutique Lambda Dispatcher. " +
        "Allows replying via WhatsApp (EUM Social), sending SES email, " +
        "and reading SNS topic metadata.",
      managedPolicies: [
        // AWSLambdaBasicExecutionRole provides CloudWatch Logs permissions.
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    // SNS read — allows the dispatcher to inspect topic attributes if needed.
    dispatcherRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SNSReadAccess",
        effect: iam.Effect.ALLOW,
        actions: [
          "sns:GetTopicAttributes",
          "sns:ListSubscriptionsByTopic",
          "sns:ListTopics",
        ],
        resources: [inboundTopic.topicArn],
      })
    );

    // End User Messaging Social — send outbound WhatsApp messages.
    // EUM Social requires resource: "*" because the phone number resource ARN
    // is not known until a number is registered in the EUM Social console.
    dispatcherRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EUMSocialSendWhatsApp",
        effect: iam.Effect.ALLOW,
        actions: ["social-messaging:SendWhatsAppMessage"],
        // Scope to this account's EUM Social resources once the phone number
        // ARN is known. Format:
        // arn:aws:social-messaging:<region>:<account>:phone-number-id/<id>
        resources: ["*"],
      })
    );

    // SES — send outbound email (e.g. order confirmations, support replies).
    dispatcherRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SESSendEmail",
        effect: iam.Effect.ALLOW,
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        // Restrict to the verified sending identity once the domain is verified.
        // For now use "*" so the stack deploys before SES verification completes.
        resources: ["*"],
      })
    );

    // KMS — decrypt SNS messages encrypted with the topic CMK.
    dispatcherRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "TopicKMSDecrypt",
        effect: iam.Effect.ALLOW,
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: [topicKey.keyArn],
      })
    );

    // =========================================================================
    // 4. Lambda Dispatcher — function placeholder
    //
    //    The actual handler code lives in ../lambda/dispatcher and is compiled
    //    separately (see lambda/dispatcher/package.json). The asset path points
    //    to the compiled output directory. Before the first `cdk deploy` run:
    //      cd ../lambda/dispatcher && npm install && npm run build
    //
    //    EUM Social Integration point:
    //    The Lambda is subscribed to ClawBoutiqueInbound via SNS. When a
    //    customer sends a WhatsApp message to the registered phone number,
    //    EUM Social → SNS → this Lambda.
    // =========================================================================
    const dispatcherLogGroup = new logs.LogGroup(
      this,
      "DispatcherLambdaLogGroup",
      {
        logGroupName: "/aws/lambda/ClawBoutiqueDispatcher",
        retention: logs.RetentionDays.THREE_MONTHS,
        removalPolicy: RemovalPolicy.RETAIN,
      }
    );

    // -----------------------------------------------------------------------
    // Lambda code source selection
    //
    // Uses the compiled dispatcher asset from ../lambda/dispatcher/dist.
    // Build it first: cd ../lambda/dispatcher && npm install && npm run build
    // The deploy.sh script handles this automatically.
    // -----------------------------------------------------------------------
    const dispatcherCode = lambda.Code.fromAsset("../lambda/dispatcher/dist");

    const dispatcherFn = new lambda.Function(this, "ClawBoutiqueDispatcher", {
      functionName: "ClawBoutiqueDispatcher",
      description:
        "Routes SNS-wrapped inbound events (WhatsApp via EUM Social, SES email) " +
        "to the OpenClaw gateway for processing and sends replies.",
      runtime: lambda.Runtime.NODEJS_20_X,
      code: dispatcherCode,
      handler: "index.handler",
      role: dispatcherRole,
      timeout: Duration.seconds(30),
      memorySize: 256,
      logGroup: dispatcherLogGroup,
      environment: {
        // Populated at deploy time; dispatcher reads these to know where to
        // forward events and which SES identity to use.
        INBOUND_TOPIC_ARN: inboundTopic.topicArn,
        SES_FROM_ADDRESS: SUPPORT_EMAIL,
        DOMAIN: DOMAIN,
        // Set NODE_OPTIONS for source maps in error stack traces.
        NODE_OPTIONS: "--enable-source-maps",
      },
      tracing: lambda.Tracing.ACTIVE,
    });

    // Subscribe the dispatcher to the inbound topic.
    // Every WhatsApp webhook event and SES inbound notification will invoke it.
    inboundTopic.addSubscription(
      new subscriptions.LambdaSubscription(dispatcherFn)
    );

    // =========================================================================
    // 5. SES — domain identity and inbound receipt rule
    //
    //    After CDK deploy, complete domain verification manually:
    //      1. Add the CNAME / TXT / MX records to the DNS zone for DOMAIN.
    //      2. The MX record must point to inbound-smtp.<region>.amazonaws.com
    //         for SES receipt to work.
    //      3. Verify the domain in SES console or via `aws sesv2 create-email-identity`.
    //
    //    The receipt rule set and rule below are created but the rule set must
    //    be set as ACTIVE in the SES console (or via CLI) after deploy:
    //      aws ses set-active-receipt-rule-set \
    //        --rule-set-name ClawBoutiqueRuleSet \
    //        --region <region>
    // =========================================================================

    // Receipt rule set — the container for all inbound routing rules.
    const receiptRuleSet = new ses.ReceiptRuleSet(
      this,
      "ClawBoutiqueRuleSet",
      {
        receiptRuleSetName: "ClawBoutiqueRuleSet",
        // dropSpam adds a Lambda-based spam/virus check before processing.
        dropSpam: true,
      }
    );

    // Inbound receipt rule: emails to support@clawboutique.com are published
    // to the ClawBoutiqueInbound SNS topic for the dispatcher to handle.
    receiptRuleSet.addRule("SupportInboundRule", {
      enabled: true,
      receiptRuleName: "ClawBoutiqueSupportInbound",
      recipients: [SUPPORT_EMAIL],
      scanEnabled: true,
      tlsPolicy: ses.TlsPolicy.REQUIRE,
      actions: [
        new sesActions.Sns({
          topic: inboundTopic,
          // INCLUDE_HEADERS sends the full MIME headers in the SNS notification
          // so the dispatcher can read subject, reply-to, etc.
          encoding: sesActions.EmailEncoding.UTF8,
        }),
      ],
    });

    // =========================================================================
    // 6. Secrets Manager — DB credentials secret
    //
    //    Placeholder values are used so the secret is created during deploy.
    //    Replace actual values BEFORE the OpenClaw app starts:
    //      aws secretsmanager put-secret-value \
    //        --secret-id ClawBoutique/DbCredentials \
    //        --secret-string '{"host":"...","port":"3306","dbname":"...","username":"...","password":"..."}'
    //
    //    RemovalPolicy.RETAIN ensures the secret is not deleted when the stack
    //    is destroyed, preventing accidental loss of production credentials.
    // =========================================================================
    const dbCredentialsSecret = new secretsmanager.Secret(
      this,
      "ClawBoutiqueDbCredentials",
      {
        secretName: "ClawBoutique/DbCredentials",
        description:
          "Database credentials for the Claw Boutique OpenClaw application " +
          "running on Lightsail. Replace placeholder values before first use.",
        secretObjectValue: {
          host: SecretValue.unsafePlainText("PLACEHOLDER_DB_HOST"),
          port: SecretValue.unsafePlainText("3306"),
          dbname: SecretValue.unsafePlainText("clawboutique"),
          username: SecretValue.unsafePlainText("PLACEHOLDER_DB_USER"),
          password: SecretValue.unsafePlainText("PLACEHOLDER_DB_PASSWORD"),
        },
        removalPolicy: RemovalPolicy.RETAIN,
      }
    );

    // =========================================================================
    // 7. Lightsail IAM role — OpenClaw application access
    //
    //    The OpenClaw app on Lightsail assumes this role to read DB credentials
    //    from Secrets Manager. Because Lightsail instances cannot use EC2
    //    instance profiles directly, the role is assumed via STS:AssumeRole
    //    using long-term credentials stored on the instance, OR via an IAM
    //    Identity Center permission set if the account is enrolled.
    //
    //    Trust policy:
    //      If LIGHTSAIL_ACCOUNT_PRINCIPAL is set, trust that principal.
    //      Otherwise fall back to trusting the current AWS account root
    //      (allows any principal in the account to scope down via STS).
    //
    //    After deploy, create an IAM user / access key for the Lightsail
    //    instance and attach an inline policy that allows only sts:AssumeRole
    //    on this role ARN. Store the access key in the instance environment.
    // =========================================================================
    // Build the trust principal. If a specific Lightsail instance ARN is
    // provided via LIGHTSAIL_PRINCIPAL, trust only that ARN. Otherwise trust
    // the deploying account root (same-account only, no cross-account access).
    const lightsailPrincipal: iam.IPrincipal =
      LIGHTSAIL_ACCOUNT_PRINCIPAL.length > 0
        ? new iam.ArnPrincipal(LIGHTSAIL_ACCOUNT_PRINCIPAL)
        : new iam.AccountPrincipal(this.account);

    const lightsailRole = new iam.Role(this, "OpenClawLightsailRole", {
      roleName: "OpenClawLightsailRole",
      assumedBy: lightsailPrincipal,
      description:
        "Assumed by the OpenClaw application on Lightsail. " +
        "Grants read-only access to the Claw Boutique DB credentials secret.",
    });

    // Grant read access to the DB credentials secret only.
    // GetSecretValue is the minimum needed; DescribeSecret allows the app to
    // check the secret ARN/name without retrieving the value.
    lightsailRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadDbCredentials",
        effect: iam.Effect.ALLOW,
        actions: [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ],
        resources: [dbCredentialsSecret.secretArn],
      })
    );

    // Allow the Lightsail role to decrypt the secret if it is KMS-encrypted.
    // The DB credentials secret uses AWS-managed key by default; if you switch
    // to a CMK, add a kms:Decrypt policy on that key and grant the role here.

    // =========================================================================
    // 8. S3 Bucket + CloudFront — static website (storefront + admin dashboard)
    // =========================================================================
    const websiteBucket = new s3.Bucket(this, "ClawBoutiqueWebsite", {
      bucketName: `claw-boutique-web-${this.account}`,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });

    const distribution = new cloudfront.Distribution(
      this,
      "ClawBoutiqueDistribution",
      {
        defaultBehavior: {
          origin: origins.S3BucketOrigin.withOriginAccessControl(websiteBucket),
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        },
        defaultRootObject: "index.html",
        errorResponses: [
          {
            httpStatus: 403,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
          },
          {
            httpStatus: 404,
            responseHttpStatus: 200,
            responsePagePath: "/index.html",
          },
        ],
      }
    );

    // Deploy static files from web/static/ to S3, invalidate CloudFront cache
    new s3deploy.BucketDeployment(this, "DeployWebsite", {
      sources: [s3deploy.Source.asset("../web/static")],
      destinationBucket: websiteBucket,
      distribution,
      distributionPaths: ["/*"],
    });

    // =========================================================================
    // 9. Store API Lambda — Flask app via Mangum
    //
    //    Serves /api/* endpoints for products, orders, escalations, stats, etc.
    //    Reads DB credentials from the Secrets Manager secret.
    // =========================================================================
    const storeApiLogGroup = new logs.LogGroup(this, "StoreApiLogGroup", {
      logGroupName: "/aws/lambda/ClawBoutiqueStoreApi",
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const storeApiRole = new iam.Role(this, "StoreApiLambdaRole", {
      roleName: "ClawBoutiqueStoreApiRole",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Execution role for the Claw Boutique Store API Lambda.",
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    // Grant the Store API Lambda read access to DB credentials
    storeApiRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ReadDbCredentials",
        effect: iam.Effect.ALLOW,
        actions: [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ],
        resources: [dbCredentialsSecret.secretArn],
      })
    );

    const storeApiFn = new lambda.Function(this, "ClawBoutiqueStoreApi", {
      functionName: "ClawBoutiqueStoreApi",
      description:
        "Store API — Flask via Mangum. Serves product catalog, orders, " +
        "escalations, stats, and memory endpoints.",
      runtime: lambda.Runtime.PYTHON_3_12,
      code: lambda.Code.fromAsset("../lambda/store-api"),
      handler: "handler.handler",
      role: storeApiRole,
      timeout: Duration.seconds(30),
      memorySize: 512,
      logGroup: storeApiLogGroup,
      environment: {
        DB_SECRET_ARN: dbCredentialsSecret.secretArn,
      },
    });

    // =========================================================================
    // 10. API Gateway — REST API with API key for OpenClaw auth
    // =========================================================================
    const storeApi = new apigateway.RestApi(this, "ClawBoutiqueApi", {
      restApiName: "ClawBoutiqueStoreApi",
      description: "Store API for Claw Boutique (products, orders, admin)",
      deployOptions: {
        stageName: "prod",
        throttlingRateLimit: 50,
        throttlingBurstLimit: 100,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          "Content-Type",
          "X-Amz-Date",
          "Authorization",
          "X-Api-Key",
        ],
      },
    });

    // Proxy all requests to the Store API Lambda
    const lambdaIntegration = new apigateway.LambdaIntegration(storeApiFn);

    // Root resource
    storeApi.root.addMethod("ANY", lambdaIntegration);

    // {proxy+} catch-all
    storeApi.root
      .addResource("{proxy+}")
      .addMethod("ANY", lambdaIntegration, {
        apiKeyRequired: false,
      });

    // API key for OpenClaw to authenticate
    const openclawApiKey = storeApi.addApiKey("OpenClawApiKey", {
      apiKeyName: "OpenClawStoreApiKey",
      description: "API key used by OpenClaw tools to call the Store API",
    });

    const usagePlan = storeApi.addUsagePlan("OpenClawUsagePlan", {
      name: "OpenClawUsagePlan",
      description: "Usage plan for OpenClaw Store API access",
      throttle: {
        rateLimit: 50,
        burstLimit: 100,
      },
    });

    usagePlan.addApiKey(openclawApiKey);
    usagePlan.addApiStage({
      stage: storeApi.deploymentStage,
    });

    // Give the dispatcher the Store API URL (declared after storeApi is created)
    dispatcherFn.addEnvironment("STORE_API_URL", storeApi.url);

    // =========================================================================
    // 11. Bedrock Agent resources
    // =========================================================================

    // --- 11a. Action Group Lambda -------------------------------------------
    const agentActionGroupLogGroup = new logs.LogGroup(
      this,
      "AgentActionGroupLogGroup",
      {
        logGroupName: "/aws/lambda/ClawBoutiqueAgentActionGroup",
        retention: logs.RetentionDays.THREE_MONTHS,
        removalPolicy: RemovalPolicy.RETAIN,
      }
    );

    const agentActionGroupRole = new iam.Role(
      this,
      "AgentActionGroupLambdaRole",
      {
        roleName: "ClawBoutiqueAgentActionGroupRole",
        assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
        description:
          "Execution role for the Bedrock Agent action group Lambda. " +
          "Calls the Store API over HTTPS.",
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName(
            "service-role/AWSLambdaBasicExecutionRole"
          ),
        ],
      }
    );

    const actionGroupLambda = new lambda.Function(
      this,
      "ClawBoutiqueAgentActionGroup",
      {
        functionName: "ClawBoutiqueAgentActionGroup",
        description:
          "Handles Bedrock Agent tool calls (list_products, get_product, " +
          "get_order, create_escalation) by calling the Store API.",
        runtime: lambda.Runtime.PYTHON_3_12,
        code: lambda.Code.fromAsset("../lambda/agent-action-group"),
        handler: "handler.lambda_handler",
        role: agentActionGroupRole,
        timeout: Duration.seconds(30),
        memorySize: 256,
        logGroup: agentActionGroupLogGroup,
        environment: {
          STORE_API_URL: storeApi.url,
        },
      }
    );

    // Allow Bedrock to invoke the action group Lambda.
    actionGroupLambda.addPermission("BedrockAgentInvoke", {
      principal: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      action: "lambda:InvokeFunction",
    });

    // --- 11b. Bedrock Agent IAM role ----------------------------------------
    const bedrockAgentRole = new iam.Role(this, "BedrockAgentRole", {
      roleName: "ClawBoutiqueBedrockAgentRole",
      assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      description:
        "Role assumed by the Bedrock Agent to invoke the Nova Lite foundation model.",
    });

    bedrockAgentRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokeNovaLite",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel"],
        resources: [
          "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
        ],
      })
    );

    // --- 11c. Bedrock Agent -------------------------------------------------
    const bedrockAgent = new bedrock.CfnAgent(this, "ClawBoutiqueAgent", {
      agentName: "ClawBoutiqueAgent",
      foundationModel: "amazon.nova-lite-v1:0",
      agentResourceRoleArn: bedrockAgentRole.roleArn,
      idleSessionTtlInSeconds: 1800,
      instruction:
        "You are a shopping assistant for Claw Boutique, a women's fashion store. " +
        "Help customers browse products, check order status, and escalate issues. " +
        "Keep replies short and conversational — this is WhatsApp chat, not email. " +
        "Use plain text only, no markdown, no bullet points with asterisks. " +
        "When a customer asks about products, call list_products with relevant filters. " +
        "You CANNOT place orders. When a customer wants to buy something, give them the storefront link: https://d22y1hcx8ni0pf.cloudfront.net " +
        "and tell them to complete their purchase there. " +
        "When a customer reports a problem, use create_escalation to log it so the owner is notified. " +
        "Be friendly but brief. Never make up product details — always call a tool to get real data.",
      actionGroups: [
        {
          actionGroupName: "StoreActions",
          actionGroupExecutor: {
            lambda: actionGroupLambda.functionArn,
          },
          functionSchema: {
            functions: [
              {
                name: "list_products",
                description:
                  "Search the product catalog. Returns matching products with name, price, stock, sizes, and colors.",
                parameters: {
                  category: {
                    type: "string",
                    description:
                      "Product category filter (e.g., tops, dresses, accessories)",
                    required: false,
                  },
                  size: {
                    type: "string",
                    description: "Size filter (e.g., XS, S, M, L, XL)",
                    required: false,
                  },
                  color: {
                    type: "string",
                    description: "Color filter",
                    required: false,
                  },
                },
              },
              {
                name: "get_product",
                description:
                  "Get full details for a single product by its ID, including price, stock level, available sizes, and colors.",
                parameters: {
                  product_id: {
                    type: "integer",
                    description: "Numeric product ID",
                    required: true,
                  },
                },
              },
              {
                name: "get_order",
                description:
                  "Look up an order by order ID. Returns order status, items, and total.",
                parameters: {
                  order_id: {
                    type: "integer",
                    description: "Numeric order ID",
                    required: true,
                  },
                },
              },
              {
                name: "create_escalation",
                description:
                  "Log a customer issue or complaint so the store owner is notified. Use this when a customer has a problem that needs human follow-up.",
                parameters: {
                  customer_phone: {
                    type: "string",
                    description: "Customer WhatsApp phone number in E.164 format",
                    required: true,
                  },
                  issue: {
                    type: "string",
                    description:
                      "Short description of the issue or complaint",
                    required: true,
                  },
                  order_id: {
                    type: "integer",
                    description:
                      "Order ID related to the issue, if applicable",
                    required: false,
                  },
                },
              },
            ],
          },
        },
      ],
    });

    // --- 11d. Bedrock Agent Alias -------------------------------------------
    const bedrockAgentAlias = new bedrock.CfnAgentAlias(
      this,
      "ClawBoutiqueAgentAlias",
      {
        agentId: bedrockAgent.attrAgentId,
        agentAliasName: "live",
      }
    );

    // --- 11e. Update dispatcher Lambda env vars and IAM ---------------------
    dispatcherFn.addEnvironment(
      "BEDROCK_AGENT_ID",
      bedrockAgent.attrAgentId
    );
    dispatcherFn.addEnvironment(
      "BEDROCK_AGENT_ALIAS_ID",
      bedrockAgentAlias.attrAgentAliasId
    );

    dispatcherRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "BedrockInvokeAgent",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeAgent"],
        resources: ["arn:aws:bedrock:us-east-1:*:agent-alias/*/*"],
      })
    );

    // =========================================================================
    // 12. Stack Outputs
    // =========================================================================

    // SNS Topic ARN — paste this into the End User Messaging Social console
    // when configuring the event destination for your WhatsApp phone number.
    new CfnOutput(this, "ClawBoutiqueInboundTopicArn", {
      exportName: "ClawBoutiqueInboundTopicArn",
      value: inboundTopic.topicArn,
      description:
        "SNS topic ARN for ClawBoutiqueInbound. " +
        "Set as the event destination in the End User Messaging Social console " +
        "for the registered WhatsApp phone number.",
    });

    // Lambda Dispatcher function name — useful for CI/CD pipelines and monitoring.
    new CfnOutput(this, "DispatcherFunctionName", {
      exportName: "ClawBoutiqueDispatcherFunctionName",
      value: dispatcherFn.functionName,
      description:
        "Name of the Lambda Dispatcher function. " +
        "Use this in CloudWatch dashboards, alarms, and CI/CD pipelines.",
    });

    // Lambda Dispatcher function ARN — for cross-stack references if needed.
    new CfnOutput(this, "DispatcherFunctionArn", {
      exportName: "ClawBoutiqueDispatcherFunctionArn",
      value: dispatcherFn.functionArn,
      description: "ARN of the Lambda Dispatcher function.",
    });

    // Lightsail IAM role ARN — configure this in the OpenClaw app's
    // AWS credential configuration (e.g. ~/.aws/config role_arn).
    new CfnOutput(this, "LightsailRoleArn", {
      exportName: "OpenClawLightsailRoleArn",
      value: lightsailRole.roleArn,
      description:
        "ARN of the IAM role assumed by OpenClaw on Lightsail for Secrets Manager access.",
    });

    // DB credentials secret ARN — reference in the OpenClaw app config.
    new CfnOutput(this, "DbCredentialsSecretArn", {
      exportName: "ClawBoutiqueDbCredentialsSecretArn",
      value: dbCredentialsSecret.secretArn,
      description:
        "ARN of the Secrets Manager secret holding DB credentials. " +
        "Replace placeholder values before starting the OpenClaw application.",
    });

    // SES receipt rule set name — must be activated manually after deploy.
    new CfnOutput(this, "SesReceiptRuleSetName", {
      exportName: "ClawBoutiqueSesReceiptRuleSetName",
      value: receiptRuleSet.receiptRuleSetName,
      description:
        "Name of the SES receipt rule set. " +
        "Run: aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet",
    });

    // CloudFront website URL — buyer storefront and admin dashboard.
    new CfnOutput(this, "WebsiteUrl", {
      exportName: "ClawBoutiqueWebsiteUrl",
      value: `https://${distribution.distributionDomainName}`,
      description: "CloudFront URL for the storefront and admin dashboard.",
    });

    // Store API endpoint — used by OpenClaw tools and frontend JS.
    new CfnOutput(this, "StoreApiUrl", {
      exportName: "ClawBoutiqueStoreApiUrl",
      value: storeApi.url,
      description: "API Gateway URL for the Store API.",
    });

    // Store API key ID — retrieve the actual key value via:
    //   aws apigateway get-api-key --api-key <id> --include-value
    new CfnOutput(this, "StoreApiKeyId", {
      exportName: "ClawBoutiqueStoreApiKeyId",
      value: openclawApiKey.keyId,
      description:
        "API key ID for OpenClaw. Get the value: " +
        "aws apigateway get-api-key --api-key <id> --include-value",
    });

    // Bedrock Agent ID — used by the dispatcher to invoke the agent.
    new CfnOutput(this, "BedrockAgentId", {
      exportName: "ClawBoutiqueBedrockAgentId",
      value: bedrockAgent.attrAgentId,
      description: "ID of the Bedrock Agent (ClawBoutiqueAgent).",
    });

    // Bedrock Agent Alias ID — the 'live' alias used by the dispatcher.
    new CfnOutput(this, "BedrockAgentAliasId", {
      exportName: "ClawBoutiqueBedrockAgentAliasId",
      value: bedrockAgentAlias.attrAgentAliasId,
      description: "ID of the 'live' alias for the Bedrock Agent.",
    });
  }
}
