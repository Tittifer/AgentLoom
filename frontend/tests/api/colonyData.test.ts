import { describe, expect, it, vi } from "vitest";

import { apiClient } from "../../src/api/client";
import { listDataRows, listDataTables } from "../../src/api/colonyData";

vi.mock("../../src/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

describe("colony Data API", () => {
  it("读取业务表清单与分页行", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([]);

    await listDataTables("colony 1");
    await listDataRows("colony 1", "city research", {
      limit: 25,
      offset: 50,
      orderBy: "score",
      orderDir: "desc",
    });

    expect(apiClient.get).toHaveBeenNthCalledWith(
      1,
      "/api/colonies/colony%201/data/tables",
    );
    expect(apiClient.get).toHaveBeenNthCalledWith(
      2,
      "/api/colonies/colony%201/data/tables/city%20research/rows?limit=25&offset=50&order_dir=desc&order_by=score",
    );
  });
});
