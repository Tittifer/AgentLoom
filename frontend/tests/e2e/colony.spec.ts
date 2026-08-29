import { expect, test } from "@playwright/test";

test("创建 Colony 并与 Queen 对话", async ({ page }) => {
  await page.goto("/colonies");
  await page.getByRole("link", { name: /创建 Colony|立即创建/ }).first().click();
  const name = `E2E Colony ${Date.now()}`;
  await page.getByLabel("名称").fill(name);
  await page.getByLabel("说明").fill("验证动态 Colony 工作台");
  await page.getByRole("button", { name: "创建并进入工作台" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByLabel("发送给 Queen 的消息").fill("请开始分析");
  await page.getByRole("button", { name: "发送给 Queen" }).click();
  await expect(page.getByText("模拟 Queen 已收到消息。")).toBeVisible({ timeout: 10_000 });
});
