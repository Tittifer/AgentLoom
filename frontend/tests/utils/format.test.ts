import { describe, expect, it } from "vitest";

import { ApiClientError } from "../../src/api/client";
import { formatError, humanize } from "../../src/utils/format";

describe("format utilities", () => {
  it("translates known statuses, roles, and event types", () => {
    expect(humanize("running")).toBe("运行中");
    expect(humanize("researcher")).toBe("研究员");
    expect(humanize("node.retrying")).toBe("节点正在重试");
  });

  it("translates known API errors without exposing backend English", () => {
    const error = new ApiClientError(502, {
      code: "PLANNER_PROVIDER_ERROR",
      message: "LLM provider rejected response_format",
    });

    expect(formatError(error)).toBe("模型服务调用失败，请检查模型配置和服务状态。");
  });
});
