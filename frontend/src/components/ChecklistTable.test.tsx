import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChecklistItem } from "../api/types";
import { ChecklistSummary, ChecklistTable } from "./ChecklistTable";

const OK_ITEM: ChecklistItem = {
  work_item_id: "1",
  item_no: "壹.一.1.4.8",
  name: "水泥漆，平頂披水泥磨平刷綠建材水性水泥漆",
  result: "OK",
  chapter_code: "09912",
  chapter: { code: "09912", title: "水泥漆", version: "5.0" },
  bases: [
    { basis_type: "standard", reference: "CNS 4940", detail: "第09912章 相關準則", verification_status: null },
    { basis_type: "law", reference: "職業安全衛生法", detail: "第09912章 相關準則", verification_status: "ACTIVE" },
  ],
};

const MISSING_ITEM: ChecklistItem = {
  work_item_id: "2",
  item_no: "壹.一.1.1.5",
  name: "臨時設施，施工用臨時水電設施費",
  result: "SPEC_NOT_INCLUDED",
  chapter_code: "01510",
  chapter: null,
  bases: [],
};

describe("ChecklistSummary", () => {
  it("三個結果的筆數都看得到", () => {
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(screen.getByText("248")).toBeInTheDocument();
    expect(screen.getByText("188")).toBeInTheDocument();
    expect(screen.getByText("592")).toBeInTheDocument();
  });

  it("說明「本案規範未收錄」需要人工篩選，不是整批都是缺漏", () => {
    // 實測 188 筆裡最大的一塊是 01271 計量與計價（83 筆，44%），
    // 而施工規範書不收錄行政性章節完全合理。
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(screen.getByText(/人工/)).toBeInTheDocument();
  });
});

describe("ChecklistTable", () => {
  it("本案規範未收錄的列看得到缺的是哪一章", () => {
    render(<ChecklistTable items={[MISSING_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const row = screen.getByText("壹.一.1.1.5").closest("tr");
    expect(row).toHaveTextContent("01510");
  });

  it("查證過的法規顯示狀態", () => {
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText(/現行有效/)).toBeInTheDocument();
  });

  it("未查證的依據不顯示成「查無此法規」", () => {
    // null 是「我們沒查」，不是「查過、不存在」。顯示成查無會讓人
    // 以為規範書引用了不存在的標準。
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.queryByText(/查無此法規/)).not.toBeInTheDocument();
    expect(screen.getByText(/未查證/)).toBeInTheDocument();
  });

  it("依檢核結果篩選", () => {
    render(
      <ChecklistTable
        items={[OK_ITEM, MISSING_ITEM]}
        resultFilter="SPEC_NOT_INCLUDED"
        onResultFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
  });

  it("切換篩選時把狀態交給外層", () => {
    const onChange = vi.fn();
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={onChange} />);

    fireEvent.change(screen.getByLabelText(/檢核結果/), { target: { value: "OK" } });

    expect(onChange).toHaveBeenCalledWith("OK");
  });

  it("還沒建立檢核表時說明下一步", () => {
    render(<ChecklistTable items={[]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText(/建立檢核表/)).toBeInTheDocument();
  });
});

// 以下是畫面細節的補充測試：上面的是這個元件的契約，這裡守的是不能說錯話的地方。

describe("ChecklistTable 查證狀態的說法", () => {
  function itemWithStatus(status: string | null): ChecklistItem {
    return {
      ...OK_ITEM,
      bases: [{ basis_type: "law", reference: "某某法", detail: null, verification_status: status }],
    };
  }

  it("已修正與已廢止各自顯示自己的標籤", () => {
    render(
      <ChecklistTable
        items={[itemWithStatus("AMENDED"), { ...itemWithStatus("REPEALED"), work_item_id: "3" }]}
        resultFilter="ALL"
        onResultFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByText("已修正")).toBeInTheDocument();
    expect(screen.getByText("已廢止")).toBeInTheDocument();
  });

  it("不認得的狀態值照原樣顯示，不說成未查證，也不說成查無此法規", () => {
    // 它確實是查過的結果，只是這張表還沒有對應的中文。吞掉它或換個說法都是在說謊。
    render(
      <ChecklistTable
        items={[itemWithStatus("SOMETHING_NEW")]}
        resultFilter="ALL"
        onResultFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByText("SOMETHING_NEW")).toBeInTheDocument();
    expect(screen.queryByText(/未查證/)).not.toBeInTheDocument();
    expect(screen.queryByText(/查無此法規/)).not.toBeInTheDocument();
  });

  it("依據的名稱一律是引述，沒有查證的也照樣列出來", () => {
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const row = screen.getByText("壹.一.1.4.8").closest("tr");
    expect(row).toHaveTextContent("CNS 4940");
    expect(row).toHaveTextContent("職業安全衛生法");
  });
});

describe("ChecklistTable 章節欄", () => {
  it("對得到章節時顯示章碼與章名", () => {
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const row = screen.getByText("壹.一.1.4.8").closest("tr");
    expect(row).toHaveTextContent("09912");
    expect(row).toHaveTextContent("水泥漆");
  });

  it("請確認依據的列對不到章節時也顯示章碼，不只限本案規範未收錄", () => {
    const item: ChecklistItem = { ...MISSING_ITEM, result: "NEEDS_CONFIRMATION", chapter_code: "16050" };
    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText("壹.一.1.1.5").closest("tr")).toHaveTextContent("16050");
  });

  it("連章碼都沒有的工項留白，不硬湊", () => {
    const item: ChecklistItem = { ...MISSING_ITEM, result: "NEEDS_CONFIRMATION", chapter_code: null };
    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText("壹.一.1.1.5").closest("tr")).toHaveTextContent("—");
  });
});

describe("ChecklistTable 篩選的結果", () => {
  it("篩出來沒有任何一列時說明原因，不留一張只有表頭的空表", () => {
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="SPEC_NOT_INCLUDED" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText(/沒有符合/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // 篩選器還在，使用者才改得回去
    expect(screen.getByLabelText(/檢核結果/)).toBeInTheDocument();
  });

  it("寫出目前顯示幾筆、一共幾筆", () => {
    render(
      <ChecklistTable
        items={[OK_ITEM, MISSING_ITEM]}
        resultFilter="OK"
        onResultFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/顯示 1 筆，共 2 筆/)).toBeInTheDocument();
  });
});

describe("ChecklistSummary 的說明", () => {
  it("沒有「本案規範未收錄」的時候不談人工篩選", () => {
    render(<ChecklistSummary ok={10} specNotIncluded={0} needsConfirmation={5} />);

    expect(screen.queryByText(/人工/)).not.toBeInTheDocument();
  });

  it("有查證過的依據時，說明未查證不等於查無此法規", () => {
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(screen.getByText(/不代表這個法規或標準不存在/)).toBeInTheDocument();
    // 說明自己也不能用「查無此法規」這個說法
    expect(screen.queryByText(/查無此法規/)).not.toBeInTheDocument();
  });

  it("一條依據都沒有時，不解釋根本沒出現的「未查證」", () => {
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={1028} />);

    expect(screen.queryByText(/不代表這個法規或標準不存在/)).not.toBeInTheDocument();
  });

  it("全部都是請確認依據時，說明可能是還沒建立或沒掛規範，不替使用者猜一個", () => {
    // 沒建過檢核表的專案，GET 回來每一列都是「請確認依據」，
    // 和「建過了、但這個專案沒掛規範書」在畫面上長得一樣。
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={1028} />);

    expect(screen.getByText(/還沒有任何工項對到/)).toBeInTheDocument();
    expect(screen.getByText(/還沒建立檢核表/)).toBeInTheDocument();
    expect(screen.getByText(/沒有掛上施工規範/)).toBeInTheDocument();
  });
});
