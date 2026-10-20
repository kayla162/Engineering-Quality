import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DrawingPanel } from "./DrawingPanel";
import { api } from "../api/client";

const snapshot = {
  revision: 2,
  documents: [{ id: "d", filename: "圖說.pdf", indexed: true }],
  sheets: [{ id: "s", document_id: "d", page: 2, number: "A1-01", title: "防水詳圖", method: "text", warning: null, evidence: "原始文字" }],
  items: [{ id: "i", sheet_id: "s", name: "防水", evidence: "圖名候選", review_status: "pending",
    work_item_ids: [], suggested_work_item_ids: ["w"], review_note: "" }],
  union: [{ work_item_id: "w", item_no: "1", name: "外牆防水", status: "needs_confirmation", drawing_item_ids: [] }],
  summary: { pages: 1, unreadable_pages: 0, unindexed_documents: 0, work_items: 1, matched: 0, pending_items: 1 },
  disclaimer: "尚未找到對應不等於不存在",
};

afterEach(() => vi.restoreAllMocks());
describe("DrawingPanel", () => {
  it("notifies a completed mutation even when the drawing panel was collapsed while waiting", async () => {
    vi.spyOn(api, "getDrawings").mockResolvedValue(snapshot);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let resolveIndex!: (value: typeof snapshot) => void;
    vi.spyOn(api, "indexDrawing").mockImplementation(() => new Promise(resolve => { resolveIndex = resolve; }));
    const onChanged = vi.fn();
    render(<DrawingPanel projectId="p" onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("原始文字");
    fireEvent.click(screen.getByRole("button", { name: "建立／重建圖說索引" }));
    fireEvent.click(screen.getByRole("button", { name: "收合圖說檢核" }));
    await act(async () => resolveIndex(snapshot));
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "展開圖說檢核" })).toBeInTheDocument();
  });
  it("notifies its parent only after a successful mutation, not a read or failure", async () => {
    vi.spyOn(api, "getDrawings").mockResolvedValue(snapshot);
    const mutate = vi.spyOn(api, "indexDrawing")
      .mockRejectedValueOnce(new Error("index failed")).mockResolvedValueOnce(snapshot);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = vi.fn();
    render(<DrawingPanel projectId="p" onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("原始文字");
    expect(onChanged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重新整理" }));
    await waitFor(() => expect(api.getDrawings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(onChanged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "建立／重建圖說索引" }));
    await screen.findByText("index failed");
    expect(onChanged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "建立／重建圖說索引" }));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(api.getDrawings).toHaveBeenCalledTimes(2);
  });
  it("labels assisted transcription separately from human correction", async () => {
    vi.spyOn(api, "getDrawings").mockResolvedValue({
      ...snapshot, sheets: [{ ...snapshot.sheets[0], method: "assisted" }],
    });
    render(<DrawingPanel projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    expect(await screen.findByText(/來源：AI 圖框轉錄，待人工核對/)).toBeInTheDocument();
    expect(screen.getByText("待覆核")).toBeInTheDocument();
  });
  it("ignores an old index response after the parent refreshes the project", async () => {
    const newer = { ...snapshot, revision: 4, documents: [{ id: "d", filename: "after.pdf", indexed: true }] };
    vi.spyOn(api, "getDrawings").mockResolvedValueOnce(snapshot).mockResolvedValueOnce(newer);
    let resolveIndex!: (value: typeof snapshot) => void;
    vi.spyOn(api, "indexDrawing").mockImplementation(() => new Promise(resolve => { resolveIndex = resolve; }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const view = render(<DrawingPanel projectId="p" refreshVersion={0} />);
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("原始文字");
    fireEvent.click(screen.getByRole("button", { name: "建立／重建圖說索引" }));
    view.rerender(<DrawingPanel projectId="p" refreshVersion={1} />);
    await screen.findByRole("option", { name: "after.pdf（已索引）" });
    await act(async () => { resolveIndex(snapshot); });
    await waitFor(() => expect(screen.getByRole("option", { name: "after.pdf（已索引）" })).toBeInTheDocument());
  });
  it("loads on expansion, preserves page evidence and never claims absence", async () => {
    vi.spyOn(api, "getDrawings").mockResolvedValue(snapshot);
    render(<DrawingPanel projectId="p" />);
    expect(api.getDrawings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("原始文字");
    expect(screen.getByRole("link", { name: "查看原圖第 2 頁" })).toHaveAttribute("href", "/api/projects/p/drawings/documents/d/file#page=2");
    expect(screen.queryByText("標單有，契約圖沒有")).not.toBeInTheDocument();
    expect(screen.getByText("尚未找到對應不等於不存在")).toBeInTheDocument();
  });

  it("suggestions are not preselected; review carries explicit user selection", async () => {
    vi.spyOn(api, "getDrawings").mockResolvedValue(snapshot);
    vi.spyOn(api, "reviewDrawingItem").mockResolvedValue(snapshot);
    render(<DrawingPanel projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("圖名候選");
    fireEvent.click(screen.getByRole("button", { name: "覆核 防水" }));
    const choice = screen.getByRole("checkbox", { name: /外牆防水/ });
    expect(choice).not.toBeChecked();
    fireEvent.click(choice);
    fireEvent.change(screen.getByLabelText("覆核說明"), { target: { value: "核對原圖" } });
    fireEvent.click(screen.getByRole("button", { name: "確認配對" }));
    await waitFor(() => expect(api.reviewDrawingItem).toHaveBeenCalledWith("p", "i", {
      decision: "confirmed", work_item_ids: ["w"], note: "核對原圖", expected_revision: 2,
    }));
  });
});
