import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkItem } from "../api/types";
import { WorkItemSummary, WorkItemTable } from "./WorkItemTable";

const WITH_CHAPTER: WorkItem = {
  work_item_id: "1",
  item_no: "壹.一.1.1.1",
  name: "施工測量，基地測量及鑑界費",
  unit: "式",
  quantity: "1",
  cost_code: "0172500004",
  spec_chapter: { code: "01725", name: "公共工程施工綱要規範第01725章 施工測量" },
};

const WITHOUT_CHAPTER: WorkItem = {
  work_item_id: "2",
  item_no: "壹.一.1.3.1",
  name: "空調工程，冰水主機",
  unit: "台",
  quantity: "2",
  cost_code: null,
  spec_chapter: null,
};

describe("WorkItemSummary", () => {
  it("全部都對到章節時不多嘴", () => {
    render(<WorkItemSummary total={438} withSpecChapter={438} />);

    expect(screen.queryByText(/各機關自訂/)).not.toBeInTheDocument();
  });

  it("有未對到的工項時說明原因，避免被當成系統故障", () => {
    // 對不到章節是正常結果——共通性工項目錄本來就不涵蓋各機關自訂的專業工項。
    // 不解釋的話，590 筆空白看起來就像系統壞了。
    render(<WorkItemSummary total={1028} withSpecChapter={438} />);

    expect(screen.getByText("590")).toBeInTheDocument();
    expect(screen.getByText(/各機關自訂/)).toBeInTheDocument();
  });

  it("三個數字都看得到", () => {
    render(<WorkItemSummary total={1028} withSpecChapter={438} />);

    expect(screen.getByText("1028")).toBeInTheDocument();
    expect(screen.getByText("438")).toBeInTheDocument();
  });
});

describe("WorkItemTable", () => {
  it("對到章節的工項顯示章碼與章名", () => {
    render(<WorkItemTable items={[WITH_CHAPTER]} onlyMissing={false} onOnlyMissingChange={vi.fn()} />);

    // 章碼與章名都要在這個工項自己那一列上——「01725」字樣在章名裡也有，
    // 所以用整頁搜尋會同時命中好幾處，要縮到列的範圍才問得準。
    const row = screen.getByText("壹.一.1.1.1").closest("tr");
    expect(row).toHaveTextContent("01725");
    expect(row).toHaveTextContent("施工綱要規範第01725章 施工測量");
  });

  it("對不到章節的工項留白，不硬湊", () => {
    render(
      <WorkItemTable items={[WITHOUT_CHAPTER]} onlyMissing={false} onOnlyMissingChange={vi.fn()} />,
    );

    const row = screen.getByText("壹.一.1.3.1").closest("tr");
    expect(row).toHaveTextContent("—");
  });

  it("勾選「只看未對到」之後只剩沒有章節的工項", () => {
    render(
      <WorkItemTable
        items={[WITH_CHAPTER, WITHOUT_CHAPTER]}
        onlyMissing={true}
        onOnlyMissingChange={vi.fn()}
      />,
    );

    expect(screen.getByText("壹.一.1.3.1")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.1.1")).not.toBeInTheDocument();
  });

  it("勾選時把狀態交給外層", () => {
    const onChange = vi.fn();
    render(<WorkItemTable items={[WITH_CHAPTER]} onlyMissing={false} onOnlyMissingChange={onChange} />);

    fireEvent.click(screen.getByLabelText(/只看未對到/));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("還沒有工項時說明下一步，而不是只給一張空表", () => {
    render(<WorkItemTable items={[]} onlyMissing={false} onOnlyMissingChange={vi.fn()} />);

    expect(screen.getByText(/標單/)).toBeInTheDocument();
  });
});
