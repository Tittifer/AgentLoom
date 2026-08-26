import { expect, test } from "@playwright/test";

test("product research completes with one reviewed retry", async ({ page }) => {
  const uniqueTitle = `E2E product research ${Date.now()}`;
  await page.goto("/tasks/new");
  await page.getByLabel("Title").fill(uniqueTitle);
  await page
    .getByLabel("Goal")
    .fill("Compare Apple, Huawei, and Xiaomi products and write a sourced report");
  await page.getByLabel("Context (JSON object)").fill('{"language":"en"}');
  await page.getByRole("button", { name: "Create and plan" }).click();

  await expect(page).toHaveURL(/\/tasks\/[0-9a-f-]+$/);
  await expect(page.getByText("Agent dependency graph")).toBeVisible();
  await expect(page.getByText("Research subject A", { exact: true })).toBeVisible();
  await expect(page.getByText("Research subject B", { exact: true })).toBeVisible();
  await expect(page.getByText("Research subject C", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByText("Mock report", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".graph-node-label small", { hasText: "completed" })).toHaveCount(4);
  await expect(page.getByText("node retrying", { exact: true })).toBeVisible();

  await page.getByText("Research subject A", { exact: true }).click();
  await expect(page.getByRole("button", { name: /#1 · retrying/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /#2 · completed/ })).toBeVisible();
  await expect(page.getByText("Agent-visible messages")).toBeVisible();
});
