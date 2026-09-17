import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const NO_DOCUMENTS = { total: 0, page: 1, page_size: 20, items: [] };

const UNAVAILABLE = {
  status: "unavailable",
  sources: [
    {
      source: "taiwan_law",
      ready: false,
      detail: "找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）",
      remedy: "python scripts/sync_taiwan_law.py",
    },
  ],
};

const ALL_READY = {
  status: "ok",
  sources: [{ source: "mock", ready: true, detail: null, remedy: null }],
};

/** 用路徑前綴回傳假回應，順便驗證前端真的打了那個路徑。 */
function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const path = Object.keys(routes).find((prefix) => url.startsWith(prefix));
      if (path === undefined) throw new Error(`測試沒有準備這個路徑：${url}`);
      return new Response(JSON.stringify(routes[path]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("來源未就緒時，還沒選文件就先看得到警告", async () => {
    stubApi({ "/api/sources": UNAVAILABLE, "/api/documents": NO_DOCUMENTS });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("尚未就緒");
  });

  it("來源就緒時完全不出現警告", async () => {
    stubApi({ "/api/sources": ALL_READY, "/api/documents": NO_DOCUMENTS });

    render(<App />);

    await screen.findByText(/請先選擇或上傳一份文件/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
