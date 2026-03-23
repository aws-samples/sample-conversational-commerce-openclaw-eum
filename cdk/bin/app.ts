#!/usr/bin/env node
/**
 * Claw Boutique CDK App Entry Point
 *
 * Bootstraps the CDK application and instantiates the ClawBoutiqueStack.
 * Deploy with:
 *   npx cdk deploy --profile <aws-profile>
 *
 * The stack uses CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION so that
 * environment-specific tokens (e.g. SES receipt rule set ARNs) resolve
 * correctly at synthesis time.
 */
import "source-map-support/register";
import { App, Tags, Aspects } from "aws-cdk-lib";
import { ClawBoutiqueStack } from "../lib/claw-boutique-stack";

const app = new App();

// -----------------------------------------------------------------------
// Instantiate the single-stack deployment.
// Pass explicit env so CDK can resolve region-specific service principals
// and SES regional endpoints correctly.
// -----------------------------------------------------------------------
new ClawBoutiqueStack(app, "ClawBoutiqueStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  description:
    "Claw Boutique: SNS inbound topic, Lambda dispatcher, SES receipt rules, " +
    "Lightsail IAM role, and Secrets Manager DB credentials",
});

// Apply cost-allocation and ownership tags to every resource in the app.
Tags.of(app).add("Project", "ClawBoutique");
Tags.of(app).add("ManagedBy", "CDK");
Tags.of(app).add("Environment", "production");
