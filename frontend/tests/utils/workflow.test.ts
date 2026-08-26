import { describe, expect, it } from "vitest";

import { getNodeStatusColor } from "../../src/utils/workflow";

describe("getNodeStatusColor", () => {
  it("maps active and terminal states to distinct colors", () => {
    expect(getNodeStatusColor("running")).toBe("#2563eb");
    expect(getNodeStatusColor("completed")).toBe("#16a34a");
    expect(getNodeStatusColor("failed")).toBe("#dc2626");
  });

  it("uses the pending color for unknown states", () => {
    expect(getNodeStatusColor("unknown")).toBe("#94a3b8");
  });
});
