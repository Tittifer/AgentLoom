import { expect, test } from "@playwright/test";

test("创建、使用并删除协作会话", async ({ page }) => {
  await page.goto("/colonies");
  await page.getByRole("button", { name: "新建会话" }).first().click();
  await expect(page.getByRole("heading", { name: "新会话" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "会话导航" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /计划/ })).toBeVisible();
  const firstMessage = `请分析 E2E 目标 ${Date.now()}`;
  await page.getByLabel("输入消息").fill(firstMessage);
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("heading", { name: firstMessage })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("模拟 Queen 已收到消息。")).toBeVisible({ timeout: 10_000 });

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除" }).click();
  await expect(page.getByRole("heading", { name: "我的会话" })).toBeVisible();
  await expect(page.getByText(firstMessage)).not.toBeVisible();
});
