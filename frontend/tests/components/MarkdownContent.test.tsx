import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownContent } from "../../src/components/MarkdownContent";

describe("MarkdownContent", () => {
  it("renders headings, emphasis, lists, links, and GFM-style tables", () => {
    render(
      <MarkdownContent
        content={`## 六城横向对比

| 城市 | 特色 | 预算 |
| --- | :---: | ---: |
| 成都 | **熊猫** | 2000元 |

- 适合亲子
- 适合美食旅行

[查看详情](https://example.com)`}
      />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "六城横向对比" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("熊猫").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "查看详情" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
  });

  it("keeps raw HTML inert and rejects unsafe links", () => {
    const { container } = render(
      <MarkdownContent content={'<script>alert("xss")</script>\n\n[危险链接](javascript:alert(1))'} />,
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(screen.getByText(/<script>alert/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "危险链接" })).not.toBeInTheDocument();
    expect(screen.getByText(/^危险链接/)).toBeInTheDocument();
  });
});
