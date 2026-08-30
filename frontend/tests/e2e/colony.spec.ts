import { expect, test } from "@playwright/test";

test("创建、使用并删除协作会话", async ({ page }) => {
  await page.goto("/colonies");
  await page.getByRole("link", { name: "新建会话" }).first().click();
  const firstMessage = `请分析 E2E 目标 ${Date.now()}`;
  await page.getByLabel("输入第一条消息").fill(firstMessage);
  await page.getByRole("button", { name: "开始会话" }).click();
  await expect(page.getByRole("heading", { name: firstMessage })).toBeVisible();
  await expect(page.getByText("模拟 Queen 已收到消息。")).toBeVisible({ timeout: 10_000 });

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除会话" }).click();
  await expect(page.getByRole("heading", { name: "我的会话" })).toBeVisible();
  await expect(page.getByText(firstMessage)).not.toBeVisible();
});
