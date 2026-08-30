import { describe, expect, it } from "vitest";

import {
  formatDateTime,
  formatError,
  sessionNameFromMessage,
  statusText,
} from "../../src/utils/format";

describe("中文格式化工具", () => {
  it("转换状态和空日期", () => {
    expect(statusText("running")).toBe("运行中");
    expect(statusText("timed_out")).toBe("已超时");
    expect(formatDateTime(null)).toBe("—");
  });

  it("提取错误消息", () => {
    expect(formatError(new Error("失败原因"))).toBe("失败原因");
  });

  it("根据第一条用户消息生成会话名称", () => {
    expect(sessionNameFromMessage("  帮我\n制定旅行计划  ")).toBe("帮我 制定旅行计划");
    expect(sessionNameFromMessage("一".repeat(40))).toBe(`${"一".repeat(32)}…`);
  });
});
