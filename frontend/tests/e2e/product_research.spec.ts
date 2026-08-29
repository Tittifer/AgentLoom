import { expect, test } from "@playwright/test";

test("product research completes with one reviewed retry", async ({ page }) => {
  const uniqueTitle = `E2E product research ${Date.now()}`;
  await page.goto("/tasks/new");
  await page.getByLabel("标题").fill(uniqueTitle);
  await page
    .getByLabel("目标")
    .fill("Compare Apple, Huawei, and Xiaomi products and write a sourced report");
  await page.getByLabel("上下文（JSON 对象）").fill('{"language":"en"}');
  await page.getByRole("button", { name: "创建并规划" }).click();

  await expect(page).toHaveURL(/\/tasks\/[0-9a-f-]+$/);
  await expect(page.getByText("智能体依赖图")).toBeVisible();
  await expect(page.getByText("Research subject A", { exact: true })).toBeVisible();
  await expect(page.getByText("Research subject B", { exact: true })).toBeVisible();
  await expect(page.getByText("Research subject C", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "启动运行" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByText("Mock report", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".graph-status--completed", { hasText: "已完成" })).toHaveCount(4);
  await expect(page.getByText("节点正在重试", { exact: true })).toBeVisible();

  await page.getByText("Research subject A", { exact: true }).click();
  await expect(page.getByRole("button", { name: /#1 · 重试中/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /#2 · 已完成/ })).toBeVisible();
  await expect(page.getByText("智能体可见消息")).toBeVisible();
});
