import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Checklist, ChecklistItem } from "../api/types";
import { api } from "../api/client";
import { stubApi } from "../test/stubApi";
import { ProjectWorkItemsPage } from "./ProjectWorkItemsPage";

const PROJECT = {
  project_id: "p1",
  name: "秀山分隊興建工程",
  created_at: "2026-09-17T08:00:00Z",
};

const ONE_PROJECT = { total: 1, items: [PROJECT] };
const NO_PROJECTS = { total: 0, items: [] };
const NO_DOCUMENTS = { total: 0, page: 1, page_size: 20, items: [] };

const WORK_ITEMS = {
  total: 1028,
  with_spec_chapter: 438,
  items: [
    {
      work_item_id: "w1",
      item_no: "壹.一.1.1.1",
      name: "施工測量，基地測量及鑑界費",
      unit: "式",
      quantity: "1",
      cost_code: "0172500004",
      spec_chapter: { code: "01725", name: "公共工程施工綱要規範第01725章 施工測量" },
    },
    // 沒有對到綱要規範章節的工項：「只看未對到章節」要靠它才看得出有沒有生效
    {
      work_item_id: "w2",
      item_no: "壹.一.1.3.1",
      name: "空調工程，冰水主機",
      unit: "台",
      quantity: "2",
      cost_code: null,
      spec_chapter: null,
    },
  ],
};

const CHECKLIST_ITEM_OK: ChecklistItem = {
  work_item_id: "w1",
  item_no: "壹.一.1.4.8",
  name: "水泥漆，平頂披水泥磨平刷綠建材水性水泥漆",
  result: "OK",
  chapter_code: "09912",
  chapter: { code: "09912", title: "水泥漆", version: "5.0" },
  bases: [
    { basis_type: "standard", reference: "CNS 4940", detail: "第09912章 相關準則", verification_status: null },
    { basis_type: "law", reference: "職業安全衛生法", detail: "第09912章 相關準則", verification_status: "ACTIVE" },
    // 真實資料裡最大宗的沒查證：類型是法規、但索引裡沒有完全同名（屋內線路裝置規則是已更名的舊名稱）
    { basis_type: "law", reference: "屋內線路裝置規則", detail: "第09912章 相關準則", verification_status: null },
  ],
};

const CHECKLIST_ITEM_MISSING: ChecklistItem = {
  work_item_id: "w2",
  item_no: "壹.一.1.1.5",
  name: "臨時設施，施工用臨時水電設施費",
  result: "SPEC_NOT_INCLUDED",
  chapter_code: "01510",
  chapter: null,
  bases: [],
};

/** 同一種結果再多幾筆，讓三種結果的筆數互不相同：2、3、4。 */
function extraItem(result: ChecklistItem["result"], id: string, itemNo: string): ChecklistItem {
  const bases =
    result === "OK"
      ? [{ basis_type: "law", reference: "職業安全衛生法", detail: null, verification_status: "ACTIVE" }]
      : [];
  return { ...CHECKLIST_ITEM_MISSING, work_item_id: id, item_no: itemNo, result, bases };
}

const CONTRACT_NOTE = "契約依據為專案層級，不逐工項列出。";

// 三種結果的筆數刻意互不相同（2、3、4）。如果兩種結果一樣多，
// 摘要的兩格互換、或頁面把欄位傳錯，測試都看不出來。
const CHECKLIST: Checklist = {
  total: 9,
  summary: { ok: 2, spec_not_included: 3, needs_confirmation: 4 },
  contract_note: CONTRACT_NOTE,
  spec_warning: null,
  items: [
    CHECKLIST_ITEM_OK,
    extraItem("OK", "w3", "壹.一.1.4.9"),
    CHECKLIST_ITEM_MISSING,
    extraItem("SPEC_NOT_INCLUDED", "w4", "壹.一.1.1.6"),
    extraItem("SPEC_NOT_INCLUDED", "w5", "壹.一.1.1.7"),
    extraItem("NEEDS_CONFIRMATION", "w6", "壹.一.1.9.1"),
    extraItem("NEEDS_CONFIRMATION", "w7", "壹.一.1.9.2"),
    extraItem("NEEDS_CONFIRMATION", "w8", "壹.一.1.9.3"),
    extraItem("NEEDS_CONFIRMATION", "w9", "壹.一.1.9.4"),
  ],
};

const EMPTY_CHECKLIST: Checklist = {
  total: 0,
  summary: { ok: 0, spec_not_included: 0, needs_confirmation: 0 },
  contract_note: CONTRACT_NOTE,
  spec_warning: null,
  items: [],
};

const OTHER_PROJECT = {
  project_id: "p2",
  name: "另一個工程",
  created_at: "2026-09-18T08:00:00Z",
};

/**
 * 檢核表的 GET 與 POST 是同一個網址、卻要回不同內容（GET 讀舊的、POST 回重建的），
 * stubApi 只認路徑分不出來，所以這幾個測試自己接 fetch。
 */
function stubChecklistApi(
  checklist: (
    method: string,
    url: string,
  ) => { status: number; body: unknown } | Promise<{ status: number; body: unknown }>,
) {
  const calls: string[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);

      let reply: { status: number; body: unknown };
      if (url.endsWith("/checklist")) reply = await checklist(method, url);
      else if (url.includes("/work-items")) reply = { status: 200, body: WORK_ITEMS };
      else if (url.startsWith("/api/projects"))
        reply = { status: 200, body: { total: 2, items: [PROJECT, OTHER_PROJECT] } };
      else reply = { status: 200, body: NO_DOCUMENTS };

      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  return calls;
}

/** 頁面上「檢核表」摘要裡某個標籤所在的那一格（工項清單的摘要也有 .summary-cell，要用標籤認）。 */
function summaryCell(label: string): HTMLElement {
  const labelElement = screen
    .getAllByText(label)
    .find((element) => element.classList.contains("summary-label"));
  return labelElement?.closest(".summary-cell") as HTMLElement;
}

/** 建立檢核表的按鈕，不管它現在寫的是「建立檢核表」還是「建立中…」。 */
function buildButton(): HTMLElement {
  return screen.getByRole("button", { name: /建立檢核表|建立中/ });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProjectWorkItemsPage", () => {
  it.each(["review", "checklist"])("refreshes integrated data after %s succeeds without reloading drawings", async (action) => {
    stubApi({
      "/api/projects/p1/work-items": WORK_ITEMS,
      "/api/projects/p1/checklist": EMPTY_CHECKLIST,
      "/api/projects": ONE_PROJECT,
      "/api/documents": NO_DOCUMENTS,
    });
    const drawing = {
      revision: 1, documents: [{ id: "d", filename: "fixture.pdf", indexed: true }],
      sheets: [{ id: "s", document_id: "d", page: 1, number: "A1", title: "測試圖",
        method: "text", evidence: "測試原文", warning: null }],
      items: [{ id: "i", sheet_id: "s", name: "待覆核候選", evidence: "圖說候選",
        review_status: "pending", work_item_ids: [], suggested_work_item_ids: [], review_note: "" }],
      union: [], summary: { pages: 1, unreadable_pages: 0, unindexed_documents: 0,
        work_items: 0, matched: 0, pending_items: 1 }, disclaimer: "需人工核對",
    };
    vi.spyOn(api, "getDrawings").mockResolvedValue(drawing);
    vi.spyOn(api, "reviewDrawingItem").mockResolvedValue({ ...drawing, revision: 2 });
    vi.spyOn(api, "buildChecklist").mockResolvedValue(EMPTY_CHECKLIST);
    const integrated = {
      project_id: "p1", revision: 1, total: 0, summary: {}, warnings: ["整合資料更新前"],
      contract_note: "待確認", items: [],
    };
    vi.spyOn(api, "getIntegratedChecklist").mockResolvedValueOnce(integrated)
      .mockResolvedValue({ ...integrated, revision: 2, warnings: ["整合資料已更新"] });
    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    fireEvent.click(await screen.findByRole("button", { name: "展開整合檢核" }));
    await screen.findByText("整合資料更新前");
    fireEvent.click(screen.getByRole("button", { name: "展開圖說檢核" }));
    await screen.findByText("測試原文");
    if (action === "review") {
      fireEvent.click(screen.getByRole("button", { name: "覆核 待覆核候選" }));
      fireEvent.change(screen.getByLabelText("覆核說明"), { target: { value: "人工核對測試" } });
      fireEvent.click(screen.getByRole("button", { name: "排除此候選" }));
    } else {
      fireEvent.click(buildButton());
    }
    await screen.findByText("整合資料已更新");
    await waitFor(() => expect(api.getIntegratedChecklist).toHaveBeenCalledTimes(2));
    expect(api.getDrawings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("測試原文")).toBeInTheDocument();
  });
  it("還沒有專案時引導使用者先建立一個", async () => {
    stubApi({ "/api/projects": NO_PROJECTS, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);

    expect(await screen.findByText(/先建立一個專案/)).toBeInTheDocument();
  });

  it("選定專案後載入它的工項並顯示統計", async () => {
    stubApi({
      "/api/projects/p1/work-items": WORK_ITEMS,
      "/api/projects/p1/checklist": EMPTY_CHECKLIST,
      "/api/projects": ONE_PROJECT,
      "/api/documents": NO_DOCUMENTS,
    });

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    // 工項清單預設收合，要展開才看得到列與統計
    fireEvent.click(await screen.findByRole("button", { name: /展開工項清單/ }));

    expect(await screen.findByText("1028")).toBeInTheDocument();
    expect(screen.getByText("438")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.1")).toBeInTheDocument();
  });

  it("建立專案時打的是 POST /api/projects", async () => {
    const calls = stubApi({ "/api/projects": ONE_PROJECT, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);
    fireEvent.change(await screen.findByLabelText(/專案名稱/), {
      target: { value: "新工程" },
    });
    fireEvent.click(screen.getByRole("button", { name: /建立專案/ }));

    expect(await screen.findByText("秀山分隊興建工程")).toBeInTheDocument();
    expect(calls).toContain("POST /api/projects");
  });

  it("名稱是空的時候不送出", async () => {
    const calls = stubApi({ "/api/projects": NO_PROJECTS, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /建立專案/ }));

    expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(0);
  });

  it("選定專案後一併載入檢核表，而且不會自己重建", async () => {
    const calls = stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));

    expect(await screen.findByText("壹.一.1.4.8")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(calls).toContain("GET /api/projects/p1/checklist");
    // 整頁（含所有說明文字）都不能出現「查無此法規」：沒查的依據顯示「未查證」，不是「查無」
    expect(screen.getAllByText("未查證").length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent(/查無此法規/);
    // 重建很貴、而且有副作用，只能由使用者按按鈕觸發
    expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(0);
  });

  it("按「建立檢核表」打 POST，並換成重建後的結果", async () => {
    const calls = stubChecklistApi((method) =>
      method === "POST"
        ? { status: 201, body: CHECKLIST }
        : { status: 200, body: EMPTY_CHECKLIST },
    );

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    expect(await screen.findByText(/還沒有可檢核的工項/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /建立檢核表/ }));

    expect(await screen.findByText("壹.一.1.4.8")).toBeInTheDocument();
    expect(calls).toContain("POST /api/projects/p1/checklist");
  });

  it("規範書解析品質不佳的警告要顯示出來", async () => {
    stubChecklistApi(() => ({
      status: 200,
      body: { ...CHECKLIST, spec_warning: "本案施工規範書的解析品質不佳：頁首版本讀不到。依據可能不完整。" },
    }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));

    expect(await screen.findByText(/解析品質不佳/)).toBeInTheDocument();
  });

  it("沒有警告的時候不出現警告", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    expect(screen.queryByText(/解析品質不佳/)).not.toBeInTheDocument();
  });

  it("契約欄去哪了：契約是專案層級的依據，這句話要跟著檢核表顯示", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));

    expect(await screen.findByText(CONTRACT_NOTE)).toBeInTheDocument();
  });

  it("換到另一個專案時，不會把上一個專案的檢核表留在畫面上", async () => {
    // 第二個專案的檢核表載入失敗：如果畫面只是「沒更新」，使用者會在
    // 「另一個工程」的標題底下看到「秀山分隊興建工程」的列。
    stubChecklistApi((_method, url) =>
      url.includes("/p1/")
        ? { status: 200, body: CHECKLIST }
        : { status: 500, body: { error: { code: "INTERNAL", message: "檢核表壞了" } } },
    );

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    fireEvent.click(screen.getByText("另一個工程"));

    expect(await screen.findByText("檢核表壞了")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
  });

  it("重建到一半換了專案，重建完成不會蓋掉另一個專案的畫面", async () => {
    // 重建要好幾秒。這段時間使用者可能已經切到別的專案；
    // 舊專案的回應回來時，只能存進舊專案自己名下。
    const other: Checklist = {
      ...CHECKLIST,
      items: [{ ...CHECKLIST_ITEM_MISSING, work_item_id: "x1", item_no: "貳.九.9.9" }],
    };
    let finishRebuild: (reply: { status: number; body: unknown }) => void = () => {};
    const rebuild = new Promise<{ status: number; body: unknown }>((resolve) => {
      finishRebuild = resolve;
    });

    stubChecklistApi((method, url) => {
      if (method === "POST") return rebuild;
      return { status: 200, body: url.includes("/p1/") ? CHECKLIST : other };
    });

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");
    fireEvent.click(screen.getByRole("button", { name: /建立檢核表/ }));
    // 先確定重建真的在進行中，再換專案；不然下面等「建立中…」結束的同步點
    // 在標籤被拿掉時會立刻成立，測試就在 POST 還沒處理前提早通過
    await screen.findByRole("button", { name: "建立中…" });

    fireEvent.click(screen.getByText("另一個工程"));
    expect(await screen.findByText("貳.九.9.9")).toBeInTheDocument();

    finishRebuild({ status: 201, body: CHECKLIST });
    // 等「建立中…」結束，確認回應已經處理完
    await screen.findByRole("button", { name: "建立檢核表" });

    expect(screen.getByText("貳.九.9.9")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
  });

  it("摘要的三個數字各在自己標籤的格子裡，不是頁面上某處有就好", async () => {
    // 這個專案的檢核表是 2 個 OK、3 個本案規範未收錄、4 個請確認依據，三個數字互不相同。
    // 頁面把欄位傳錯（例如 ok 傳成 spec_not_included）時，只查「頁面上有這個數字」是看不出來的。
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    expect(summaryCell("OK")).toHaveTextContent(/^2OK$/);
    expect(summaryCell("本案規範未收錄")).toHaveTextContent(/^3本案規範未收錄$/);
    expect(summaryCell("請確認依據")).toHaveTextContent(/^4請確認依據$/);
  });

  it("兩個區塊的標題前面都沒有夾著一整張表：排在後面的那個標題不必捲過另一張表才找得到", async () => {
    // 兩張一千多列的表疊在同一頁，排第二的那張就等於找不到（實測差了十幾萬像素）。
    // jsdom 量不了像素，所以用結構來釘：文件順序裡較後的那個標題，前面不能有任何表格的列。
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    const headings = [
      screen.getByRole("heading", { name: "檢核表" }),
      screen.getByRole("heading", { name: "工項清單" }),
    ].sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    const later = headings[1];

    const rowsAbove = [...document.querySelectorAll("tbody tr")].filter(
      (row) => later.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_PRECEDING,
    );
    expect(rowsAbove).toHaveLength(0);
  });

  it("工項清單預設收合：列不渲染，只留標題和展開按鈕（寫出筆數）", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    const toggle = await screen.findByRole("button", { name: "展開工項清單（共 1028 筆）" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("heading", { name: "工項清單" })).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.1.1")).not.toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.3.1")).not.toBeInTheDocument();
    // 頁面上只剩檢核表那一張表
    expect(screen.getAllByRole("table")).toHaveLength(1);
  });

  it("展開後看得到工項列與統計，再收合又藏起來", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    fireEvent.click(await screen.findByRole("button", { name: "展開工項清單（共 1028 筆）" }));

    expect(await screen.findByText("壹.一.1.1.1")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.3.1")).toBeInTheDocument();
    expect(screen.getByText("438")).toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(2);
    const collapse = screen.getByRole("button", { name: "收合工項清單" });
    expect(collapse).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(collapse);

    expect(screen.queryByText("壹.一.1.1.1")).not.toBeInTheDocument();
    expect(screen.queryByText("438")).not.toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /展開工項清單/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("展開、收合都不動檢核表：列還在，篩選也還在", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");
    const select = screen.getByLabelText(/檢核結果/) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "SPEC_NOT_INCLUDED" } });

    fireEvent.click(await screen.findByRole("button", { name: /展開工項清單/ }));
    await screen.findByText("壹.一.1.1.1");
    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
    expect(select.value).toBe("SPEC_NOT_INCLUDED");

    fireEvent.click(screen.getByRole("button", { name: "收合工項清單" }));
    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
    expect(select.value).toBe("SPEC_NOT_INCLUDED");
    // 檢核表的摘要、建立按鈕也都沒受影響
    expect(summaryCell("OK")).toHaveTextContent(/^2OK$/);
    expect(screen.getByRole("button", { name: "建立檢核表" })).toBeEnabled();
  });

  it("收合再展開，「只看未對到章節」的勾選還在，不會被重設", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    fireEvent.click(await screen.findByRole("button", { name: /展開工項清單/ }));
    fireEvent.click(await screen.findByLabelText(/只看未對到/));
    expect(screen.getByText("壹.一.1.3.1")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.1.1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "收合工項清單" }));
    fireEvent.click(screen.getByRole("button", { name: /展開工項清單/ }));

    expect(screen.getByLabelText(/只看未對到/)).toBeChecked();
    expect(screen.getByText("壹.一.1.3.1")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.1.1")).not.toBeInTheDocument();
  });

  it("收合與展開不會重新向後端要資料", async () => {
    // 工項與檢核表都存在頁面的 state 裡；收合只是不畫，不是丟掉。
    const calls = stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    fireEvent.click(await screen.findByRole("button", { name: /展開工項清單/ }));
    await screen.findByText("壹.一.1.1.1");
    fireEvent.click(screen.getByRole("button", { name: "收合工項清單" }));
    fireEvent.click(screen.getByRole("button", { name: /展開工項清單/ }));
    await screen.findByText("壹.一.1.1.1");

    expect(calls.filter((call) => call.includes("/work-items"))).toHaveLength(1);
    expect(calls.filter((call) => call.endsWith("/checklist"))).toHaveLength(1);
  });

  it("頁面上的篩選真的接到表格：選「本案規範未收錄」只剩那三列，選回「全部」又全部回來", async () => {
    // 篩選的元件測試用 vi.fn() 當外層，頁面沒把 onResultFilterChange 接到 state 時看不出來。
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");
    const select = screen.getByLabelText(/檢核結果/);

    fireEvent.change(select, { target: { value: "SPEC_NOT_INCLUDED" } });

    expect(screen.getByText("壹.一.1.1.5")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.6")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.7")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.9.1")).not.toBeInTheDocument();
    expect(screen.getByText(/顯示 3 筆，共 9 筆/)).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "ALL" } });

    expect(screen.getByText("壹.一.1.4.8")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.9.4")).toBeInTheDocument();
    expect(screen.getByText(/顯示 9 筆，共 9 筆/)).toBeInTheDocument();
  });

  it("重建進行中：按鈕寫「建立中…」而且停用，連點不會送出第二次重建", async () => {
    // 重建要好幾秒，這段時間再按一次就是兩次重建同時跑。
    let finishRebuild: (reply: { status: number; body: unknown }) => void = () => {};
    const rebuild = new Promise<{ status: number; body: unknown }>((resolve) => {
      finishRebuild = resolve;
    });
    const calls = stubChecklistApi((method) =>
      method === "POST" ? rebuild : { status: 200, body: EMPTY_CHECKLIST },
    );

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText(/還沒有可檢核的工項/);

    fireEvent.click(buildButton());

    const building = await screen.findByRole("button", { name: "建立中…" });
    expect(building).toBeDisabled();
    fireEvent.click(building);
    fireEvent.click(building);
    expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(1);

    finishRebuild({ status: 201, body: CHECKLIST });

    const done = await screen.findByRole("button", { name: "建立檢核表" });
    expect(done).toBeEnabled();
    expect(await screen.findByText("壹.一.1.4.8")).toBeInTheDocument();
    expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(1);
  });

  it("依據是法規、查不到完全同名的，頁面上顯示未查證，整頁沒有「查無」兩個字", async () => {
    stubChecklistApi(() => ({ status: 200, body: CHECKLIST }));

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));
    await screen.findByText("壹.一.1.4.8");

    const row = screen.getByText("壹.一.1.4.8").closest("tr") as HTMLElement;
    const lawRow = within(row).getByText("屋內線路裝置規則").closest("li") as HTMLElement;
    expect(lawRow).toHaveTextContent("未查證");
    expect(document.body).not.toHaveTextContent(/查無/);
  });
});
