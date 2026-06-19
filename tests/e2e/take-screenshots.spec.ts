import { test } from "@playwright/test";
import * as path from "path";

const STORE_URL = "https://d1yis8p165yfn1.cloudfront.net";
const ADMIN_URL = `${STORE_URL}/admin.html`;
const DOCS_DIR = "../../docs";
const MOCKUPS_PATH = `file://${path.resolve(__dirname, "../../docs/mockups.html")}`;

test("take storefront screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(STORE_URL);
  await page.locator(".product-card").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-storefront.png` });
});

test("take admin dashboard screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(ADMIN_URL);
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-admin-dashboard.png` });
});

test("take admin orders screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(ADMIN_URL);
  await page.waitForTimeout(4000);
  await page.locator("#nav-desktop-sidebar-nav-orders").click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-admin-orders.png` });
});

test("take admin escalations screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(ADMIN_URL);
  await page.waitForTimeout(4000);
  await page.locator("#nav-desktop-sidebar-nav-escalations").click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-admin-escalations.png` });
});

test("take storefront checkout screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(STORE_URL);
  await page.locator(".product-card").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(1000);
  // Add item to cart
  await page.locator("button:has-text('Add to Cart')").first().click();
  await page.waitForTimeout(500);
  // Open cart
  await page.locator("#cart-btn").click();
  await page.waitForTimeout(500);
  // Click checkout
  await page.locator("#checkout-btn").click();
  await page.waitForTimeout(500);
  // Fill form with demo data
  await page.fill("#customer_name", "Sarah Chen");
  await page.fill("#customer_email", "sarah@email.com");
  await page.fill("#customer_phone", "+15550001234");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-checkout.png` });
});

test("take admin products screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(ADMIN_URL);
  await page.waitForTimeout(4000);
  await page.locator("#nav-desktop-sidebar-nav-products").click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-admin-products.png` });
});

test("take admin insights screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(ADMIN_URL);
  await page.waitForTimeout(4000);
  await page.locator("#nav-desktop-sidebar-nav-insights").click();
  await page.waitForTimeout(6000);
  await page.screenshot({ path: `${DOCS_DIR}/screenshot-admin-insights.png` });
});

// ── Mockup screenshots ──────────────────────────────────────────────────────

async function captureMockup(page: any, id: string, outFile: string) {
  await page.goto(MOCKUPS_PATH);
  await page.waitForTimeout(500);
  const el = page.locator(`#${id}`);
  await el.screenshot({ path: `${DOCS_DIR}/${outFile}` });
}

test("capture whatsapp order mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "wa-order", "mockup-wa-order.png");
});

test("capture whatsapp survey mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "wa-survey", "mockup-wa-survey.png");
});

test("capture whatsapp cart mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "wa-cart", "mockup-wa-cart.png");
});

test("capture email confirmation mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "email-confirmation", "mockup-email-confirmation.png");
});

test("capture email stock mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "email-stock", "mockup-email-stock.png");
});

test("capture email escalation mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "email-escalation", "mockup-email-escalation.png");
});

test("capture telegram stock alert mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "tg-stock", "mockup-tg-stock.png");
});

test("capture telegram review escalation mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "tg-escalation", "mockup-tg-escalation.png");
});

test("capture telegram order notification mockup", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await captureMockup(page, "tg-order", "mockup-tg-order.png");
});
