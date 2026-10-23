import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Dashboard, RegulationChange } from "../api/types";
import { stubApi } from "../test/stubApi";
import { DashboardPage } from "./DashboardPage";

const DASHBOARD: Dashboard = {
  documents: { total: 3, by_status: { ANALYZED: 3 }, degraded: 1, failed: 0 },
  references: {
    total: 12,
    by_status: { ACTIVE: 7, REPEALED: 2, POSSIBLE_MATCH: 3 },
    by_review: { UNREVIEWED: 10, CONFIRMED: 2 },
    needs_action: 4,
    by_source: { mock: 9 },
  },
  projects: 1,
  open_regulation_changes: 1,
  top_regulations: [
    { regulation_id: "r1", name: "政府採購法", status: "ACTIVE", source: "mock", references: 5, documents: 3 },
  ],
  documents_needing_action: [
    { document_id: "d1", filename: "品質計畫.docx", parse_quality: "OK", references: 8, unreviewed: 6, needs_action: 4 },
  ],
};

const CHANGE: RegulationChange = {
  change_id: "c1",
  regulation_id: "r2",
  regulation_name: "勞工安全衛生法",
  current_status: "REPEALED",
  source: "mock",
  changes: { status: { old: "ACTIVE", new: "REPEALED" } },
  detected_at: "2026-10-24T01:00:00Z",
  acknowledged_at: null,
  acknowledged_by: null,
  affected_documents: [{ document_id: "d1", filename: "品質計畫.docx", references: 2 }],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage(canCheckChanges = true, onOpenDocument = vi.fn()) {
  render(<DashboardPage canCheckChanges={canCheckChanges} onOpenDocument={onOpenDocument} />);
  return onOpenDocument;
}

describe("DashboardPage", () => {
  it("顯示待處理數與待確認異動數", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 0, items: [] } });

    renderPage();

    const cell = (await screen.findByText("待處理引用")).closest(".summary-cell") as HTMLElement;
    expect(cell).toHaveTextContent("4");
    expect(screen.getByText("待確認法規異動").closest(".summary-cell")).toHaveTextContent("1");
  });

  it("比對到假資料時明確警告", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 0, items: [] } });

    renderPage();

    expect(await screen.findByText(/9 筆引用比對到假資料/)).toBeInTheDocument();
  });

  it("解析品質不佳的文件數要看得到", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 0, items: [] } });

    renderPage();

    expect(await screen.findByText(/1 份文件解析品質不佳/)).toBeInTheDocument();
  });

  it("點待處理文件會打開那份文件", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 0, items: [] } });

    const onOpen = renderPage();
    fireEvent.click(await screen.findByText("品質計畫.docx"));

    expect(onOpen).toHaveBeenCalledWith("d1");
  });

  it("法規異動列出變動內容與受影響文件", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 1, items: [CHANGE] } });

    renderPage();

    expect(await screen.findByText("勞工安全衛生法")).toBeInTheDocument();
    expect(screen.getByText(/狀態：現行有效 →/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "品質計畫.docx" })).toBeInTheDocument();
  });

  it("按「已處理」會送出確認", async () => {
    const calls = stubApi({
      "/api/dashboard": DASHBOARD,
      "/api/regulation-changes": { total: 1, items: [CHANGE] },
      "/api/regulation-changes/c1/acknowledge": CHANGE,
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "已處理" }));

    await screen.findByText("勞工安全衛生法");
    await vi.waitFor(() =>
      expect(calls).toContain("POST /api/regulation-changes/c1/acknowledge"),
    );
  });

  it("一般成員看不到「立即檢查」", async () => {
    stubApi({ "/api/dashboard": DASHBOARD, "/api/regulation-changes": { total: 0, items: [] } });

    renderPage(false);

    await screen.findByText("待處理引用");
    expect(screen.queryByRole("button", { name: "立即檢查" })).not.toBeInTheDocument();
  });

  it("檢查結果會說出有幾部沒檢查到、為什麼", async () => {
    stubApi({
      "/api/dashboard": DASHBOARD,
      "/api/regulation-changes/check": {
        checked: 5,
        changed: 0,
        skipped: [{ regulation_id: "r9", name: "某辦法", reason: "來源 pcces 未啟用" }],
        new_changes: [],
      },
      "/api/regulation-changes": { total: 0, items: [] },
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "立即檢查" }));

    expect(await screen.findByRole("status")).toHaveTextContent("已檢查 5 部法規，新異動 0 筆，1 部未能檢查");
    expect(screen.getByText("某辦法：來源 pcces 未啟用")).toBeInTheDocument();
  });
});
