import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Checklist, ChecklistItem } from "../api/types";
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

const CONTRACT_NOTE = "契約依據為專案層級，不逐工項列出。";

const CHECKLIST: Checklist = {
  total: 2,
  summary: { ok: 1, spec_not_included: 1, needs_confirmation: 0 },
  contract_note: CONTRACT_NOTE,
  spec_warning: null,
  items: [CHECKLIST_ITEM_OK, CHECKLIST_ITEM_MISSING],
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProjectWorkItemsPage", () => {
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

    fireEvent.click(screen.getByText("另一個工程"));
    expect(await screen.findByText("貳.九.9.9")).toBeInTheDocument();

    finishRebuild({ status: 201, body: CHECKLIST });
    // 等「建立中…」結束，確認回應已經處理完
    await screen.findByRole("button", { name: "建立檢核表" });

    expect(screen.getByText("貳.九.9.9")).toBeInTheDocument();
    expect(screen.queryByText("壹.一.1.4.8")).not.toBeInTheDocument();
  });
});
