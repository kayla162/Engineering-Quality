import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchPage } from "../pages/SearchPage";
import { type DemoData, demoBackend } from "./DemoApp";

const DATA: DemoData = {
  note: "示範版：回答是評估時的真實輸出",
  section_note: "示範版只收錄法規條文",
  items: [
    {
      id: "s02",
      group: "一般問題",
      question: "溝挖到一米五以上要不要做支撐",
      knowledge: {
        query: "溝挖到一米五以上要不要做支撐",
        mode: "hybrid",
        vector_enabled: true,
        method_note: "混合搜尋",
        hits: [
          { ref: "營造安全衛生設施標準 第 71 條", kind: "law_article", source: "營造安全衛生設施標準",
            locator: "第 71 條", heading: "第五章露天開挖", snippet: "應設擋土支撐", score: 0.016, ranks: { vector: 1 } },
        ],
      },
      answer: {
        question: "溝挖到一米五以上要不要做支撐",
        status: "answered",
        answer: "要，深度一點五公尺以上應設擋土支撐。",
        citations: [{ ref: "營造安全衛生設施標準 第 71 條", quote: "應設擋土支撐", verified: true, problem: null }],
        retrieved: ["營造安全衛生設施標準 第 71 條"],
        model: "claude-opus-5-5",
        prompt_version: "qa_v1",
      },
    },
  ],
};

describe("靜態展示版", () => {
  it("點預設問題就顯示預錄的回答與搜尋結果，不呼叫任何 API", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const presets = DATA.items.map(({ group, question }) => ({ group, question }));

    render(<SearchPage onOpenDocument={vi.fn()} backend={demoBackend(DATA, 0)} presets={presets} />);
    fireEvent.click(screen.getByRole("button", { name: "溝挖到一米五以上要不要做支撐" }));

    expect(await screen.findByText("要，深度一點五公尺以上應設擋土支撐。")).toBeInTheDocument();
    expect(screen.getByText("✓ 已比對原文")).toBeInTheDocument();
    expect(await screen.findByText("語意第 1 名")).toBeInTheDocument();
    expect(screen.getByLabelText(/關鍵字/)).toHaveAttribute("readonly");
    expect(screen.getByText(/展示版只能選上方的預設問題/)).toBeInTheDocument();
    // 展示版沒有上傳文件：文件段落與法規名稱區塊不顯示，免得看起來像「查不到」
    expect(screen.queryByText(/相關段落/)).not.toBeInTheDocument();
    expect(screen.queryByText(/相關法規/)).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("不在清單裡的問題會說明只能回答列出的問題", async () => {
    await expect(demoBackend(DATA, 0).answerQuestion("別的問題")).rejects.toThrow("示範版只能回答");
  });
});
