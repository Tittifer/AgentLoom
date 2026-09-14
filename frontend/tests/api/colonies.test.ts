import { describe, expect, it, vi } from "vitest";

import { apiClient } from "../../src/api/client";
import { createSession, type SessionRead } from "../../src/api/colonies";

vi.mock("../../src/api/client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const session = {
  id: "session-1",
  queen_id: "queen-1",
} as SessionRead;

describe("createSession", () => {
  it("合并同一 Queen 同时发起的重复创建请求，并在完成后允许再次创建", async () => {
    let resolveCreate!: (value: SessionRead) => void;
    vi.mocked(apiClient.post).mockReturnValueOnce(new Promise((resolve) => {
      resolveCreate = resolve as (value: SessionRead) => void;
    }));
    const payload = { queen_id: "queen-1" };

    const first = createSession(payload);
    const duplicate = createSession(payload);

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(duplicate).toBe(first);
    resolveCreate(session);
    await Promise.all([first, duplicate]);

    vi.mocked(apiClient.post).mockResolvedValueOnce({ ...session, id: "session-2" });
    await createSession(payload);
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });
});
