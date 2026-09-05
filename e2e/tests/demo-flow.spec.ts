import { test, expect, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL || "rachel.brathab@gmail.com";
const PASSWORD = process.env.E2E_PASSWORD || "TestPassword123!";

/** Login and wait for redirect to overview page. */
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign In" }).click();
  // Wait for navigation to overview
  await page.waitForURL("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test.describe("Transaction Twin Demo Flow", () => {
  test("full end-to-end demo", async ({ page }) => {
    // ── Step 1: Login ──────────────────────────────────────────
    await login(page);

    // ── Step 2: Verify Policies ────────────────────────────────
    await page.getByRole("link", { name: "Policies" }).click();
    await page.waitForURL("/policies");
    await expect(page.getByRole("heading", { name: "Policies" })).toBeVisible();

    // Verify "High Value Transaction Policy" exists and is active
    const hvPolicy = page.locator("text=High Value Transaction Policy");
    await expect(hvPolicy).toBeVisible();
    // Check that it shows "active" badge
    await expect(
      page.locator("text=active").first()
    ).toBeVisible();

    // Verify "Payment Risk Control" exists and is active
    await expect(page.locator("text=Payment Risk Control")).toBeVisible();

    // ── Step 3: Verify Transactions ────────────────────────────
    await page.getByRole("link", { name: "Transactions" }).click();
    await page.waitForURL("/transactions");
    await expect(page.getByRole("heading", { name: "Transactions" })).toBeVisible();

    // Verify BLOCK transaction (₹500,000) exists
    await expect(page.locator("text=500,000").first()).toBeVisible();
    await expect(page.locator("text=block").first()).toBeVisible();

    // Verify ALLOW transaction (₹10,000) exists
    await expect(page.locator("text=10,000").first()).toBeVisible();
    await expect(page.locator("text=allow").first()).toBeVisible();

    // Click a transaction to see details
    await page.locator("text=500,000").first().click();
    // Wait for detail panel
    await expect(page.getByText("Transaction Detail")).toBeVisible();
    // Verify decision reason is shown
    await expect(page.getByText("High Value Transaction Policy")).toBeVisible();
    // Close detail
    await page.getByRole("button", { name: "Close" }).click();

    // ── Step 4: Verify Risk Intelligence ────────────────────────
    await page.getByRole("link", { name: "Risk Intelligence" }).click();
    await page.waitForURL("/risk-intelligence");
    await expect(page.getByRole("heading", { name: "Risk Intelligence" })).toBeVisible();

    // Verify summary cards exist
    await expect(page.locator("text=Total Decisions")).toBeVisible();
    await expect(page.locator("text=Allow").first()).toBeVisible();
    await expect(page.locator("text=Block").first()).toBeVisible();

    // Verify we have decisions (> 0)
    const totalDecisions = page.locator("text=Total Decisions").locator("..").locator("..").locator("p.text-2xl");
    await expect(totalDecisions).not.toHaveText("0");

    // ── Step 5: Verify Audit Vault ──────────────────────────────
    await page.getByRole("link", { name: "Audit Vault" }).click();
    await page.waitForURL("/audit-vault");
    await expect(page.getByRole("heading", { name: "Audit Vault" })).toBeVisible();

    // Verify decision events exist
    await expect(page.locator("text=decision_created").first()).toBeVisible();

    // ── Step 6: Verify Calibration ──────────────────────────────
    await page.getByRole("link", { name: "Calibration" }).click();
    await page.waitForURL("/calibration");
    await expect(page.getByRole("heading", { name: "Calibration Intelligence" })).toBeVisible();

    // Verify calibration page has tabs
    await expect(page.getByRole("button", { name: "Versions" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Recommendations" })).toBeVisible();

    // ── Step 7: Verify Agents ───────────────────────────────────
    await page.getByRole("link", { name: "Agents" }).click();
    await page.waitForURL("/agents");
    await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();

    // Verify Payment Assistant agent exists
    await expect(page.locator("text=Payment Assistant")).toBeVisible();
  });
});
