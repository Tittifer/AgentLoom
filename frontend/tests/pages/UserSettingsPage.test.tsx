import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getUserSettings, updateUserSettings } from "../../src/api/settings";
import { UserSettingsPage } from "../../src/pages/UserSettingsPage";

vi.mock("../../src/api/settings", () => ({
  getUserSettings: vi.fn(),
  updateUserSettings: vi.fn(),
}));

describe("UserSettingsPage", () => {
  beforeEach(() => {
    vi.mocked(getUserSettings).mockResolvedValue({
      configured: false,
      model: null,
      protocol: null,
      base_url: null,
      api_key_configured: false,
      response_format: "json_schema",
      max_context_tokens: 128000,
      updated_at: null,
    });
    vi.mocked(updateUserSettings).mockResolvedValue({
      configured: true,
      model: "deepseek-v4-flash",
      protocol: "openai",
      base_url: "https://api.deepseek.com",
      api_key_configured: true,
      response_format: "json_object",
      max_context_tokens: 64000,
      updated_at: "2026-09-07T00:00:00Z",
    });
  });

  it("保存所有 Queen 共用的 LLM 配置", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><UserSettingsPage /></QueryClientProvider>);

    await userEvent.type(await screen.findByLabelText("模型名称"), "deepseek-v4-flash");
    await userEvent.type(screen.getByLabelText(/服务 Base URL/), "https://api.deepseek.com");
    await userEvent.type(screen.getByLabelText(/API Key/), "secret-key");
    await userEvent.selectOptions(screen.getByLabelText("响应格式"), "json_object");
    const context = screen.getByLabelText(/上下文窗口/);
    await userEvent.clear(context);
    await userEvent.type(context, "64000");
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(vi.mocked(updateUserSettings).mock.calls[0]?.[0]).toEqual({
      model: "deepseek-v4-flash",
      base_url: "https://api.deepseek.com",
      api_key: "secret-key",
      response_format: "json_object",
      max_context_tokens: 64000,
    });
  });
});
