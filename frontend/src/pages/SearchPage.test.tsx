import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SearchResult } from "../api/types";
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

afterEach(() => {
  vi.unstubAllGlobals();
});

async function search(term: string) {
  fireEvent.change(screen.getByLabelText(/關鍵字/), { target: { value: term } });
  fireEvent.click(screen.getByRole("button", { name: "搜尋" }));
}

describe("SearchPage", () => {
  it("送出查詢並列出段落與法規", async () => {
    const calls = stubApi({ "/api/search": RESULT });

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("混凝土澆置");

    expect(await screen.findByText("品質計畫.txt")).toBeInTheDocument();
    expect(screen.getByText("混凝土澆置作業標準")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("/api/search?q="))).toBe(true);
  });

  it("標出命中的字", async () => {
    stubApi({ "/api/search": RESULT });

    render(<SearchPage onOpenDocument={vi.fn()} />);
    await search("混凝土澆置");

    const marks = await screen.findAllByText((_, element) => element?.tagName === "MARK");
    expect(marks.length).toBeGreaterThan(0);
  });

  it("說明這不是語意搜尋", async () => {
    stubApi({ "/api/search": RESULT });

    render(<SearchPage onOpenDocument={vi.fn()} />);

    expect(screen.getByText(/不是語意模型/)).toBeInTheDocument();
  });

  it("點段落會打開那份文件", async () => {
    stubApi({ "/api/search": RESULT });
    const onOpen = vi.fn();

    render(<SearchPage onOpenDocument={onOpen} />);
    await search("混凝土澆置");
    fireEvent.click(await screen.findByText("品質計畫.txt"));

    expect(onOpen).toHaveBeenCalledWith("d1");
  });
});
