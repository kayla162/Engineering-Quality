import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { stubApi } from "./test/stubApi";

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

const NO_PROJECTS = { total: 0, items: [] };

/** App 先問 /api/auth/me，沒登入只會看到登入頁 */
const SIGNED_IN = {
  "/api/auth/me": {
    user_id: "u1",
    username: "admin",
    role: "tenant_admin",
    tenant_id: "t1",
    tenant_name: "測試租戶",
    must_change_password: false,
  },
};

const ALL_READY = {
  status: "ok",
  sources: [{ source: "mock", ready: true, detail: null, remedy: null }],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("來源未就緒時，還沒選文件就先看得到警告", async () => {
    stubApi({ ...SIGNED_IN, "/api/sources": UNAVAILABLE, "/api/documents": NO_DOCUMENTS });

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("尚未就緒");
  });

  it("來源就緒時完全不出現警告", async () => {
    stubApi({ ...SIGNED_IN, "/api/sources": ALL_READY, "/api/documents": NO_DOCUMENTS });

    render(<App />);

    await screen.findByText(/請先選擇或上傳一份文件/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("可以切到專案工項，看到專案面板", async () => {
    stubApi({ ...SIGNED_IN, "/api/sources": ALL_READY, "/api/documents": NO_DOCUMENTS, "/api/projects": NO_PROJECTS });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "專案工項" }));

    expect(await screen.findByLabelText(/專案名稱/)).toBeInTheDocument();
  });

  it("預設停在文件分析", async () => {
    stubApi({ ...SIGNED_IN, "/api/sources": ALL_READY, "/api/documents": NO_DOCUMENTS });

    render(<App />);

    expect(await screen.findByText(/請先選擇或上傳一份文件/)).toBeInTheDocument();
  });
});
