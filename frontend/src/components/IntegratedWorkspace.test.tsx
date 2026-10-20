import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { IntegratedWorkspace } from "./IntegratedWorkspace";

const fixture = {
  project_id: "p", revision: 4, total: 1, summary: { work_items: 0, matched: 0, pending_items: 1 },
  warnings: ["尚未提供標單，不能判定缺項"], contract_note: "契約適用順序待確認",
  items: [{
    key: "drawing:i", work_item_id: null, item_no: null, name: "防水工項",
    source_status: "drawing_candidate", basis_result: null, chapter_code: null, chapter: null, bases: [],
    drawings: [{ id: "i", sheet_id: "s", document_id: "d", filename: "圖說.pdf", page: 2,
      number: "A1", title: "防水詳圖", evidence: "採用塗膜防水工法", sheet_evidence: "",
      review_status: "pending", review_note: "原人工註記", warning: null }],
    method: { status: "pending", candidates: [{ text: "塗膜防水工法", source: "圖內文字", evidence: "採用塗膜防水工法" }] },
  }],
};
afterEach(() => vi.restoreAllMocks());

describe("IntegratedWorkspace", () => {
  it("places high and medium priority references before informational records across pagination", async () => {
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValue(fixture);
    const info = Array.from({ length: 50 }, (_, i) => ({
      id: `info${i}`, kind: "reference", priority: "info", source_page: 1, source_number: "A1",
      title: `一般引用${i + 1}`, message: "已定位", quote: null, document_id: null, document_url: null, targets: [],
    }));
    vi.spyOn(api, "getDrawingInspection").mockResolvedValue({
      project_id: "p", available: true, revision: 1, historical_revision: 1, warnings: [],
      summary: { current_candidates: 0, current_name_groups: 0, current_statuses: {},
        historical_name_groups: 0, historical_similar_hints: 0, index_title_differences: 0,
        references: 52, reference_counts: {} },
      groups: [], similar_hints: [], images: [], historical_summary: {},
      findings: [...info, { ...info[0], id: "medium", priority: "medium", title: "中優先核對" },
        { ...info[0], id: "high", priority: "high", title: "高優先核對" }],
    });
    const view = render(<IntegratedWorkspace projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    fireEvent.click(await screen.findByRole("button", { name: "名稱分組與核對疑義" }));
    await screen.findByText("A1 一般引用1");
    expect(Array.from(view.container.querySelectorAll(".inspection-finding summary"))
      .slice(0, 3).map(element => element.textContent?.trim()))
      .toEqual(["A1 高優先核對", "A1 中優先核對", "A1 一般引用1"]);
    expect(screen.getByText("引用與核對事項")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜尋整合工項"), { target: { value: "一般引用50" } });
    expect(screen.getByText("A1 一般引用50")).toBeInTheDocument();
  });
  it("clamps the work-item page after refresh shrinks 51 rows to 50 and labels stale review", async () => {
    const items = Array.from({ length: 51 }, (_, i) => ({
      ...fixture.items[0], key: `drawing:${i}`, name: `測試工項${i + 1}`,
      drawings: [{ ...fixture.items[0].drawings[0], review_status: "stale" }],
    }));
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValueOnce({ ...fixture, total: 51, items })
      .mockResolvedValueOnce({ ...fixture, total: 50, items: items.slice(0, 50) });
    const view = render(<IntegratedWorkspace projectId="p" refreshVersion={0} />);
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    await screen.findByText("測試工項1");
    fireEvent.click(screen.getByRole("button", { name: "工項下一頁" }));
    expect(screen.getByText("測試工項51")).toBeInTheDocument();
    view.rerender(<IntegratedWorkspace projectId="p" refreshVersion={1} />);
    expect(await screen.findByText("測試工項1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "工項上一頁" })).toBeDisabled();
    expect(screen.getByText("1–50／50 筆")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("證據與工法候選")[0]);
    expect(screen.getAllByText(/已過期，待重新核對/).length).toBeGreaterThan(0);
  });

  it("clamps both inspection pages when refreshed findings and groups shrink from 51 to 50", async () => {
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValue(fixture);
    const groups = Array.from({ length: 51 }, (_, i) => ({
      id: `g${i}`, key: `group${i}`, names: [`群組${i + 1}`], occurrence_count: 1, page_count: 1, items: [],
    }));
    const findings = Array.from({ length: 51 }, (_, i) => ({
      id: `f${i}`, kind: "title_difference", priority: "high", source_page: null, source_number: null,
      title: `疑義${i + 1}`, message: "待核對", quote: null, document_id: null, document_url: null, targets: [],
    }));
    const inspection = {
      project_id: "p", available: true, revision: 9, historical_revision: 4, warnings: [],
      summary: { current_candidates: 51, current_name_groups: 51, current_statuses: {},
        historical_name_groups: 51, historical_similar_hints: 0, index_title_differences: 51,
        references: 0, reference_counts: {} },
      groups, findings, similar_hints: [], images: [], historical_summary: {},
    };
    vi.spyOn(api, "getDrawingInspection").mockResolvedValueOnce(inspection).mockResolvedValueOnce({
      ...inspection, groups: groups.slice(0, 50), findings: findings.slice(0, 50),
    });
    render(<IntegratedWorkspace projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    fireEvent.click(await screen.findByRole("button", { name: "名稱分組與核對疑義" }));
    await screen.findByText("群組1 · 1 筆／1 頁");
    fireEvent.click(screen.getByRole("button", { name: "分組下一頁" }));
    fireEvent.click(screen.getByRole("button", { name: "疑義下一頁" }));
    expect(screen.getByText("群組51 · 1 筆／1 頁")).toBeInTheDocument();
    expect(screen.getByText("疑義51")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新讀取資料" }));
    expect(await screen.findByText("群組1 · 1 筆／1 頁")).toBeInTheDocument();
    expect(screen.getByText("疑義1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "分組上一頁" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "疑義上一頁" })).toBeDisabled();
  });
  it("loads only when opened and preserves candidate and method uncertainty", async () => {
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValue(fixture);
    render(<IntegratedWorkspace projectId="p" />);
    expect(api.getIntegratedChecklist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    expect(await screen.findByText("防水工項")).toBeInTheDocument();
    expect(screen.getByText("尚未提供標單，不能判定缺項")).toBeInTheDocument();
    expect(screen.getByText("未指定・有待核對候選")).toBeInTheDocument();
    fireEvent.click(screen.getByText("證據與工法候選"));
    expect(screen.getByText("原人工註記")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A1 · 第 2 頁" })).toHaveAttribute("href", "/api/projects/p/drawings/documents/d/file#page=2");
    expect(screen.getByRole("link", { name: "匯出 Excel" })).toHaveAttribute("href", "/api/projects/p/integrated-checklist/export?format=xlsx");
    expect(screen.queryByText("標單缺項")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜尋整合工項"), { target: { value: "不存在的工項" } });
    expect(screen.queryByText("防水工項")).not.toBeInTheDocument();
    expect(screen.getByText("沒有符合條件的資料。")).toBeInTheDocument();
  });

  it("shows historical findings separately from current review status", async () => {
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValue(fixture);
    vi.spyOn(api, "getDrawingInspection").mockResolvedValue({
      project_id: "p", available: true, revision: 9, historical_revision: 4,
      warnings: ["歷史快照"], summary: { current_candidates: 1, current_name_groups: 1, current_statuses: { confirmed: 1 },
        historical_name_groups: 1, historical_similar_hints: 0, index_title_differences: 1, references: 3, reference_counts: {} },
      groups: [{ id: "g", key: "防水", names: ["防水"], occurrence_count: 1, page_count: 1,
        items: [{ id: "i", name: "防水", sheet_id: "s", document_id: "d", page: 2, number: "A1", title: "詳圖",
          review_status: "confirmed", review_note: "已看原圖", document_url: "/api/projects/p/drawings/documents/d/file#page=2" }] }],
      similar_hints: [], findings: [{ id: "f", kind: "title_difference", priority: "high", source_page: 2, source_number: "A1",
        title: "圖名差異", message: "目錄與圖框不同", quote: "原圖文字", document_id: "d", document_url: null, targets: [] }],
      images: [], historical_summary: {},
    });
    render(<IntegratedWorkspace projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    fireEvent.click(await screen.findByRole("button", { name: "名稱分組與核對疑義" }));
    expect(await screen.findByText(/歷史核對版本 4/)).toBeInTheDocument();
    expect(screen.getByText("目錄與圖框不同")).toBeInTheDocument();
    fireEvent.click(screen.getByText("防水 · 1 筆／1 頁"));
    expect(screen.getByText("已確認")).toBeInTheDocument();
    expect(screen.getByText("已看原圖")).toBeInTheDocument();
  });

  it("ignores a late response from another project", async () => {
    let resolveOld!: (v: typeof fixture) => void;
    vi.spyOn(api, "getIntegratedChecklist").mockImplementation((id) => id === "p"
      ? new Promise(resolve => { resolveOld = resolve; })
      : Promise.resolve({ ...fixture, project_id: "q", total: 0, items: [] }));
    const view = render(<IntegratedWorkspace projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開整合檢核" }));
    await waitFor(() => expect(api.getIntegratedChecklist).toHaveBeenCalledWith("p"));
    view.rerender(<IntegratedWorkspace projectId="q" />);
    await screen.findByText("沒有符合條件的資料。");
    await act(async () => resolveOld(fixture));
    expect(screen.queryByText("防水工項")).not.toBeInTheDocument();
  });
});
