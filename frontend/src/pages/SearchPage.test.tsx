import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeSearchResult, RegulationAnswer, SearchResult } from "../api/types";
import { stubApi } from "../test/stubApi";
import { SearchPage } from "./SearchPage";

const RESULT: SearchResult = {
  query: "混凝土澆置",
  method_note: "示範檢索：依字詞（相鄰兩字）相似度排序，不是語意模型；換個說法可能就找不到。",
  sections: [
    {
      document_id: "d1",
      filename: "品質計畫.txt",
      page: 3,
      snippet: "混凝土澆置依 QP-07-03 辦理",
      score: 0.76,
      matched: ["混凝", "凝土", "土澆", "澆置"],
    },
  ],
  regulations: [
    { regulation_id: "r1", name: "混凝土澆置作業標準", status: "ACTIVE", source: "enterprise", score: 0.9 },
  ],
};

const KNOWLEDGE: KnowledgeSearchResult = {
  query: "開挖多深要做擋土",
  mode: "hybrid",
  vector_enabled: true,
  method_note: "混合搜尋：指名的條號或章碼優先，其餘依字詞相似度與語意向量的名次合併（RRF）。",
  hits: [
    {
      ref: "營造安全衛生設施標準 第 71 條",
      kind: "law_article",
      source: "營造安全衛生設施標準",
      locator: "第 71 條",
      heading: "第五章露天開挖",
      snippet: "其深度在一點五公尺以上，使勞工進入開挖面作業者，應設擋土支撐。",
      score: 0.032,
      ranks: { lexical: 3, vector: 1 },
    },
    {
      ref: "PCCES 02256",
      kind: "spec_chapter",
      source: "施工綱要規範",
      locator: "02256",
      heading: "臨時擋土支撐工法",
      snippet: "",
      score: 0.016,
      ranks: { exact: 1 },
    },
  ],
};

const ANSWER: RegulationAnswer = {
  question: "溝挖多深要做支撐",
  status: "answered",
  answer: "開挖深度在一點五公尺以上、且勞工要進入開挖面作業時，應設擋土支撐。",
  citations: [
    { ref: "營造安全衛生設施標準 第 71 條", quote: "其深度在一點五公尺以上", verified: true, problem: null },
    { ref: "建築法 第 69 條", quote: "挖土一律要做支撐", verified: false, problem: "引文不在該條原文裡（可能改寫、拼湊或引錯條）" },
  ],
  retrieved: ["營造安全衛生設施標準 第 71 條", "建築法 第 69 條"],
  model: "claude-opus-5-5",
  prompt_version: "qa_v1",
};

const ROUTES = { "/api/search": RESULT, "/api/search/knowledge": KNOWLEDGE };

async function askAi(term: string) {
  fireEvent.change(screen.getByLabelText(/關鍵字/), { target: { value: term } });
  fireEvent.click(screen.getByRole("button", { name: "問 AI" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function search(term: string) {
  fireEvent.change(screen.getByLabelText(/關鍵字/), { target: { value: term } });
  fireEvent.click(screen.getByRole("button", { name: "搜尋" }));
}

describe("SearchPage", () => {
  it("送出查詢並列出段落與法規", async () => {
    const calls = stubApi(ROUTES);

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("混凝土澆置");

    expect(await screen.findByText("品質計畫.txt")).toBeInTheDocument();
    expect(screen.getByText("混凝土澆置作業標準")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("/api/search?q="))).toBe(true);
  });

  it("標出命中的字", async () => {
    stubApi(ROUTES);

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("混凝土澆置");

    const marks = await screen.findAllByText((_, element) => element?.tagName === "MARK");
    expect(marks.length).toBeGreaterThan(0);
  });

  it("說明文件段落不是語意搜尋", async () => {
    stubApi(ROUTES);

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("混凝土澆置");

    expect(await screen.findByText(/不是語意模型/)).toBeInTheDocument();
  });

  it("列出法規條文與規範章節，並說明命中方式", async () => {
    stubApi(ROUTES);

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("開挖多深要做擋土");

    expect(await screen.findByText("營造安全衛生設施標準 第 71 條")).toBeInTheDocument();
    expect(screen.getByText("字詞第 3 名、語意第 1 名")).toBeInTheDocument();
    expect(screen.getByText("施工綱要規範 02256")).toBeInTheDocument();
    expect(screen.getByText("指名條號")).toBeInTheDocument();
  });

  it("依選擇的方式搜尋法規", async () => {
    const calls = stubApi(ROUTES);

    render(<SearchPage onOpenDocument={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/法規搜尋方式/), { target: { value: "lexical" } });
    await search("轉包");

    await screen.findByText("營造安全衛生設施標準 第 71 條");
    expect(calls.some((call) => call.includes("/api/search/knowledge?q=") && call.includes("mode=lexical"))).toBe(true);
  });

  it("點段落會打開那份文件", async () => {
    stubApi(ROUTES);
    const onOpen = vi.fn();

    render(<SearchPage onOpenDocument={onOpen} />);
    await search("混凝土澆置");
    fireEvent.click(await screen.findByText("品質計畫.txt"));

    expect(onOpen).toHaveBeenCalledWith("d1");
  });

  it("問 AI：顯示回答，並標出每條引用有沒有通過驗證", async () => {
    const calls = stubApi({ ...ROUTES, "/api/search/answer": ANSWER });

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await askAi("溝挖多深要做支撐");

    expect(await screen.findByText(/應設擋土支撐。$/)).toBeInTheDocument();
    expect(screen.getByText("✓ 已比對原文")).toBeInTheDocument();
    expect(screen.getByText(/未通過驗證：引文不在該條原文裡/)).toBeInTheDocument();
    expect(calls).toContain("POST /api/search/answer");
  });

  it("問 AI：引用都沒通過驗證時不顯示回答", async () => {
    stubApi({ ...ROUTES, "/api/search/answer": { ...ANSWER, status: "unverified", answer: "", citations: [] } });

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await askAi("溝挖多深要做支撐");

    expect(await screen.findByText(/為避免誤導不顯示回答/)).toBeInTheDocument();
    expect(screen.queryByText(/應設擋土支撐。$/)).not.toBeInTheDocument();
  });

  it("問 AI：條文不足時照實說", async () => {
    stubApi({
      ...ROUTES,
      "/api/search/answer": { ...ANSWER, status: "insufficient", answer: "提供的條文沒有規定加班時數。", citations: [] },
    });

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await askAi("工人每天加班幾小時算違法");

    expect(await screen.findByText("提供的條文不足以回答這個問題：")).toBeInTheDocument();
    expect(screen.getByText("提供的條文沒有規定加班時數。")).toBeInTheDocument();
  });
});
