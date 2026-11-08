import { useEffect, useState } from "react";

import type { KnowledgeSearchResult, RegulationAnswer } from "../api/types";
import { SearchPage, type SearchBackend } from "../pages/SearchPage";

/** 靜態展示版（VITE_DEMO=1）：讀 public/demo-data.json，不呼叫任何 API、不需要登入。 */
export interface DemoData {
  note: string;
  section_note: string;
  items: {
    id: string;
    group: string;
    question: string;
    knowledge: KnowledgeSearchResult;
    answer: RegulationAnswer;
  }[];
}

/** 讓人感覺到「有在處理」的短暫停頓；真實回答約 7 秒，這裡不假裝成真的在呼叫模型。 */
const THINKING_MS = 1200;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function demoBackend(data: DemoData, delay = THINKING_MS): SearchBackend {
  const find = (q: string) => {
    const item = data.items.find((i) => i.question === q);
    if (!item) throw new Error("示範版只能回答上方列出的問題");
    return item;
  };
  return {
    search: async (q) => ({ query: q, method_note: data.section_note, sections: [], regulations: [] }),
    searchKnowledge: async (q) => find(q).knowledge,
    answerQuestion: async (q) => {
      await wait(delay);
      return find(q).answer;
    },
  };
}

export default function DemoApp() {
  const [data, setData] = useState<DemoData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}demo-data.json`)
      .then((response) => response.json() as Promise<DemoData>)
      .then(setData, () => setError("無法載入示範資料"));
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>工程法規符合性檢查平台</h1>
          <p className="hint">
            靜態展示版 ·{" "}
            <a href="https://github.com/kayla162/Engineering-Quality">GitHub 原始碼與評估報告</a>
          </p>
        </div>
      </header>
      {data && <p className="demo-banner">{data.note}</p>}
      {error && <p className="error">{error}</p>}
      {data && (
        <SearchPage
          onOpenDocument={() => undefined}
          backend={demoBackend(data)}
          presets={data.items.map(({ group, question }) => ({ group, question }))}
        />
      )}
    </div>
  );
}
