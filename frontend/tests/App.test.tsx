import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "../src/App";

describe("App", () => {
  it.each(["/colonies/colony-1", "/sessions/session-1"])(
    "为工作台路由启用全屏布局：%s",
    (path) => {
      const { container } = render(
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<App />}>
              <Route path="colonies/:colonyId" element={<div>Colony</div>} />
              <Route path="sessions/:sessionId" element={<div>Session</div>} />
            </Route>
          </Routes>
        </MemoryRouter>,
      );

      expect(container.querySelector("main")).toHaveClass("workspace-container");
    },
  );
});
