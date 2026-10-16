import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Basis, ChecklistItem } from "../api/types";
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

/** 某個工項在某一欄的那一格。欄位位置從表頭算，不寫死第幾欄。 */
function cellOf(itemNo: string, column: string): HTMLElement {
  const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
  const row = screen.getByText(itemNo).closest("tr") as HTMLElement;
  return within(row).getAllByRole("cell")[headers.indexOf(column)];
}

/** 摘要裡某個標籤所在的那一格。數字要在自己標籤的格子裡，不能只是「頁面上某處有這個數字」。 */
function summaryCell(label: string): HTMLElement {
  const labelElement = screen
    .getAllByText(label)
    .find((element) => element.classList.contains("summary-label"));
  return labelElement?.closest(".summary-cell") as HTMLElement;
}

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
    // 依據欄在沒有依據時也是「—」，所以斷言要縮到章節那一格，不然章節欄壞了也看不出來
    const item: ChecklistItem = { ...MISSING_ITEM, result: "NEEDS_CONFIRMATION", chapter_code: null };
    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(cellOf("壹.一.1.1.5", "章節")).toHaveTextContent("—");
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

  it("全部都是請確認依據時，把可能的原因都列出來，不替使用者猜一個", () => {
    // 沒建過檢核表的專案，GET 回來每一列都是「請確認依據」；建過了但沒掛規範書，
    // 或掛了規範書、但對得到的章節都沒列出相關準則，數字也是 0／0／N。
    // 三種在畫面上長得一樣，所以三種都要說。
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={1028} />);

    expect(screen.getByText(/目前沒有任何工項列得出依據/)).toBeInTheDocument();
    expect(screen.getByText(/還沒建立檢核表/)).toBeInTheDocument();
    expect(screen.getByText(/沒有掛上施工規範/)).toBeInTheDocument();
    expect(screen.getByText(/都沒有列出相關準則/)).toBeInTheDocument();
  });

  it("不宣稱「沒有任何工項對到規範書的章節」：章對得到、只是沒列相關準則，數字也是 0／0／N", () => {
    // 後端 _result_for：章在規範書裡、但沒有抽到依據，一樣是「請確認依據」。
    // 那種情況下「沒有任何工項對到章節」是假的。
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={1028} />);

    expect(screen.queryByText(/對到本案規範書的章節/)).not.toBeInTheDocument();
  });

  it("全部都是請確認依據時，不重複說「請確認依據」是什麼意思", () => {
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={1028} />);

    expect(screen.queryByText(/沒辦法替這個工項找到依據/)).not.toBeInTheDocument();
  });

  it("只要有一個工項是 OK，就不說「沒有任何工項列得出依據」", () => {
    render(<ChecklistSummary ok={3} specNotIncluded={0} needsConfirmation={10} />);

    expect(screen.queryByText(/目前沒有任何工項列得出依據/)).not.toBeInTheDocument();
  });

  it("只要有「本案規範未收錄」的工項，就不說「沒有任何工項列得出依據」", () => {
    render(<ChecklistSummary ok={0} specNotIncluded={5} needsConfirmation={10} />);

    expect(screen.queryByText(/目前沒有任何工項列得出依據/)).not.toBeInTheDocument();
  });

  it("三個數字都是 0 的時候也不說「沒有任何工項列得出依據」", () => {
    render(<ChecklistSummary ok={0} specNotIncluded={0} needsConfirmation={0} />);

    expect(screen.queryByText(/目前沒有任何工項列得出依據/)).not.toBeInTheDocument();
  });

  it("有些工項有依據、有些要確認時，說明「請確認依據」是什麼意思", () => {
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(screen.getByText(/沒辦法替這個工項找到依據/)).toBeInTheDocument();
  });

  it("沒有任何工項是請確認依據時，不解釋它", () => {
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={0} />);

    expect(screen.queryByText(/沒辦法替這個工項找到依據/)).not.toBeInTheDocument();
  });
});

describe("ChecklistSummary 的數字跟標籤對得上", () => {
  it("每個數字都在自己標籤的格子裡，換格、輪替都不行", () => {
    // 只查「頁面上有 248」的話，三個格子互換或輪替也過得了。
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(within(summaryCell("OK")).getByText("248")).toBeInTheDocument();
    expect(within(summaryCell("本案規範未收錄")).getByText("188")).toBeInTheDocument();
    expect(within(summaryCell("請確認依據")).getByText("592")).toBeInTheDocument();
  });

  it("別的格子裡沒有這個數字", () => {
    render(<ChecklistSummary ok={248} specNotIncluded={188} needsConfirmation={592} />);

    expect(summaryCell("OK")).not.toHaveTextContent(/188|592/);
    expect(summaryCell("本案規範未收錄")).not.toHaveTextContent(/248|592/);
    expect(summaryCell("請確認依據")).not.toHaveTextContent(/248|188/);
  });
});

describe("ChecklistTable 沒查證的依據，不分依據的類型", () => {
  // 真實資料裡最大宗的沒查證不是標準，而是「類型是法規、但索引裡沒有完全同名」的：
  // 屋內線路裝置規則（已更名的舊名稱）就是 law、而且是 null。只測標準的話，
  // 把 law 的 null 顯示成「查無此法規」也過得了。
  const LAW_UNVERIFIED: Basis = {
    basis_type: "law",
    reference: "屋內線路裝置規則",
    detail: "第16401章 相關準則",
    verification_status: null,
  };

  it("類型是法規、查不到完全同名的依據顯示「未查證」", () => {
    const item: ChecklistItem = { ...OK_ITEM, bases: [LAW_UNVERIFIED] };
    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const bases = cellOf("壹.一.1.4.8", "依據");
    expect(bases).toHaveTextContent("屋內線路裝置規則");
    expect(within(bases).getByText("未查證")).toBeInTheDocument();
    expect(bases).not.toHaveTextContent(/查無/);
    // 沒查證的用淡色字，不是標籤
    expect(bases.querySelector(".badge")).toBeNull();
  });

  it("同一列裡：標準沒查證、法規沒查證、法規查到了，各是各的", () => {
    const item: ChecklistItem = {
      ...OK_ITEM,
      bases: [
        { basis_type: "standard", reference: "CNS 4940", detail: null, verification_status: null },
        LAW_UNVERIFIED,
        { basis_type: "law", reference: "職業安全衛生法", detail: null, verification_status: "ACTIVE" },
      ],
    };
    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const bases = cellOf("壹.一.1.4.8", "依據");
    expect(within(bases).getAllByText("未查證")).toHaveLength(2);
    expect(within(bases).getAllByText("現行有效")).toHaveLength(1);
    expect(bases).not.toHaveTextContent(/查無/);
  });

  it("後端沒回 verification_status 這個欄位時當成未查證，不讓整頁壞掉", () => {
    // 舊版後端（例如沒帶 --reload 的 uvicorn）的回應沒有這個欄位：值是 undefined，不是 null。
    // 沒有 error boundary，這裡丟出例外整棵樹都會消失。
    const stale = { basis_type: "law", reference: "屋內線路裝置規則", detail: null } as unknown as Basis;
    const item: ChecklistItem = { ...OK_ITEM, bases: [stale] };

    render(<ChecklistTable items={[item]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(within(cellOf("壹.一.1.4.8", "依據")).getByText("未查證")).toBeInTheDocument();
  });
});

describe("ChecklistTable 篩選選單", () => {
  const THREE_RESULTS: ChecklistItem[] = [
    OK_ITEM,
    MISSING_ITEM,
    { ...MISSING_ITEM, work_item_id: "3", item_no: "壹.一.1.9.9", result: "NEEDS_CONFIRMATION" },
  ];

  it("選項的值與標籤一個一個對得上", () => {
    render(<ChecklistTable items={[OK_ITEM]} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    const select = screen.getByLabelText(/檢核結果/) as HTMLSelectElement;
    expect([...select.options].map((option) => [option.value, option.text])).toEqual([
      ["ALL", "全部"],
      ["OK", "OK"],
      ["SPEC_NOT_INCLUDED", "本案規範未收錄"],
      ["NEEDS_CONFIRMATION", "請確認依據"],
    ]);
  });

  it.each(["ALL", "OK", "SPEC_NOT_INCLUDED", "NEEDS_CONFIRMATION"] as const)(
    "選單顯示的就是目前的篩選值：%s",
    (value) => {
      render(<ChecklistTable items={THREE_RESULTS} resultFilter={value} onResultFilterChange={vi.fn()} />);

      expect((screen.getByLabelText(/檢核結果/) as HTMLSelectElement).value).toBe(value);
    },
  );

  it.each(["ALL", "SPEC_NOT_INCLUDED", "NEEDS_CONFIRMATION"] as const)(
    "選到 %s 時，把這個值交給外層",
    (value) => {
      // 從 OK 出發：值沒變的話 React 不會觸發 onChange
      const onChange = vi.fn();
      render(<ChecklistTable items={THREE_RESULTS} resultFilter="OK" onResultFilterChange={onChange} />);

      fireEvent.change(screen.getByLabelText(/檢核結果/), { target: { value } });

      expect(onChange).toHaveBeenCalledTimes(1);
      expect(onChange).toHaveBeenCalledWith(value);
    },
  );

  it("選全部時三種結果的列都在", () => {
    render(<ChecklistTable items={THREE_RESULTS} resultFilter="ALL" onResultFilterChange={vi.fn()} />);

    expect(screen.getByText("壹.一.1.4.8")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.9.9")).toBeInTheDocument();
  });

  it.each([
    ["OK", "壹.一.1.4.8"],
    ["SPEC_NOT_INCLUDED", "壹.一.1.1.5"],
    ["NEEDS_CONFIRMATION", "壹.一.1.9.9"],
  ] as const)("篩 %s 只剩那一種：%s", (value, itemNo) => {
    render(<ChecklistTable items={THREE_RESULTS} resultFilter={value} onResultFilterChange={vi.fn()} />);

    const shown = screen.getAllByRole("row").slice(1);
    expect(shown).toHaveLength(1);
    expect(shown[0]).toHaveTextContent(itemNo);
  });
});
