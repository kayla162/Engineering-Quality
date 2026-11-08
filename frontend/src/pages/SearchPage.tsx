import { useState, type FormEvent, type ReactNode } from "react";

import { ApiError, api } from "../api/client";
import type {
  KnowledgeSearchMode,
  KnowledgeSearchResult,
  RegulationAnswer,
  RegulationStatus,
  SearchResult,
} from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { SOURCE_LABELS } from "../labels";

/** 把命中的詞標出來。matched 是後端回傳的詞（中文是相鄰兩字）。 */
function highlight(text: string, matched: string[]): ReactNode[] {
  const terms = matched.filter((term) => term.length > 0);
  if (terms.length === 0) return [text];
  const pattern = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, index) =>
    index % 2 === 1 ? <mark key={index}>{part}</mark> : part,
  );
}

const MODE_LABELS: Record<KnowledgeSearchMode, string> = {
  hybrid: "混合（建議）",
  lexical: "只比字詞",
  vector: "只比語意",
};

const CHANNEL_LABELS = { exact: "指名條號", lexical: "字詞", vector: "語意" } as const;

/** 這筆為什麼排在這裡：各路的名次。 */
function channels(ranks: KnowledgeSearchResult["hits"][number]["ranks"]): string {
  return (Object.keys(CHANNEL_LABELS) as (keyof typeof CHANNEL_LABELS)[])
    .filter((key) => ranks[key] !== undefined)
    .map((key) => (key === "exact" ? CHANNEL_LABELS[key] : `${CHANNEL_LABELS[key]}第 ${ranks[key]} 名`))
    .join("、");
}

/** AI 回答。只顯示通過引用驗證的回答；其他狀態照實說明，不讓人以為有答案。 */
function AnswerPanel({ result }: { result: RegulationAnswer }) {
  if (result.status === "unavailable") {
    return <p className="hint">AI 沒有啟用，無法回答。可以直接看下方檢索到的條文。</p>;
  }
  if (result.status === "unverified") {
    return (
      <p className="error">
        AI 的回答沒有任何一條引用能在條文原文裡找到，為避免誤導不顯示回答。請直接閱讀檢索到的條文：
        {result.retrieved.join("、")}
      </p>
    );
  }
  return (
    <div className="answer">
      {result.status === "insufficient" && <p className="hint">提供的條文不足以回答這個問題：</p>}
      <p>{result.answer}</p>
      {result.citations.length > 0 && (
        <ul>
          {result.citations.map((citation, index) => (
            <li key={`${citation.ref}-${index}`}>
              <strong>{citation.ref}</strong>：「{citation.quote}」{" "}
              {citation.verified ? (
                <span className="hint">✓ 已比對原文</span>
              ) : (
                <span className="error">未通過驗證：{citation.problem}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="hint">
        AI 回答（{result.model}），只根據檢索到的條文；引文已逐字比對原文，但結論仍請自行確認。
      </p>
    </div>
  );
}

/** 跨文件檢索：法規條文與規範章節（混合搜尋），以及已分析文件的段落（字詞相似度）。 */
export function SearchPage({ onOpenDocument }: { onOpenDocument: (documentId: string) => void }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<KnowledgeSearchMode>("hybrid");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [knowledge, setKnowledge] = useState<KnowledgeSearchResult | null>(null);
  const [answer, setAnswer] = useState<RegulationAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const [sections, articles] = await Promise.all([
        api.search(query.trim()),
        api.searchKnowledge(query.trim(), mode),
      ]);
      setResult(sections);
      setKnowledge(articles);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法搜尋");
    } finally {
      setBusy(false);
    }
  }

  async function ask() {
    if (query.trim().length < 2) return;
    setAsking(true);
    setError(null);
    try {
      setAnswer(await api.answerQuestion(query.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法回答");
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="card">
      <h2>跨文件搜尋</h2>
      <form className="filters" onSubmit={(event) => void submit(event)}>
        <label>
          關鍵字
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：開挖多深要做擋土支撐、建築法第 34 條、03310"
          />
        </label>
        <label>
          法規搜尋方式
          <select value={mode} onChange={(event) => setMode(event.target.value as KnowledgeSearchMode)}>
            {(Object.keys(MODE_LABELS) as KnowledgeSearchMode[]).map((key) => (
              <option key={key} value={key}>{MODE_LABELS[key]}</option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={busy || !query.trim()}>{busy ? "搜尋中…" : "搜尋"}</button>
        <button type="button" onClick={() => void ask()} disabled={asking || query.trim().length < 2}>
          {asking ? "AI 回答中…" : "問 AI"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      {answer && (
        <>
          <h3>AI 回答</h3>
          <AnswerPanel result={answer} />
        </>
      )}

      {knowledge && (
        <>
          <h3>法規條文與規範章節（{knowledge.hits.length}）</h3>
          <p className="hint">{knowledge.method_note}</p>
          {knowledge.hits.length === 0 ? (
            <p className="hint">沒有找到相關條文或章節。</p>
          ) : (
            <table>
              <thead>
                <tr><th>條文／章節</th><th>內容</th><th>命中方式</th></tr>
              </thead>
              <tbody>
                {knowledge.hits.map((hit) => (
                  <tr key={hit.ref}>
                    <td>
                      {hit.kind === "spec_chapter" ? `施工綱要規範 ${hit.locator}` : hit.ref}
                      {hit.heading && <div className="hint">{hit.heading}</div>}
                    </td>
                    <td>{hit.snippet || "（章名，目錄未收內文）"}</td>
                    <td className="hint">{channels(hit.ranks)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {result && (
        <>
          <p className="hint">文件段落：{result.method_note}只搜尋已分析過的文件。</p>
          <h3>相關法規（{result.regulations.length}）</h3>
          {result.regulations.length === 0 ? (
            <p className="hint">沒有名稱相近的法規。</p>
          ) : (
            <ul>
              {result.regulations.map((reg) => (
                <li key={reg.regulation_id}>
                  {reg.name} <StatusBadge status={reg.status as RegulationStatus} />{" "}
                  <span className="hint">{SOURCE_LABELS[reg.source] ?? reg.source}</span>
                </li>
              ))}
            </ul>
          )}

          <h3>相關段落（{result.sections.length}）</h3>
          {result.sections.length === 0 ? (
            <p className="hint">沒有找到相關段落。</p>
          ) : (
            <table>
              <thead>
                <tr><th>文件</th><th>頁碼</th><th>段落</th><th>相似度</th></tr>
              </thead>
              <tbody>
                {result.sections.map((hit, index) => (
                  <tr key={`${hit.document_id}-${index}`} className="clickable" onClick={() => onOpenDocument(hit.document_id)}>
                    <td>{hit.filename}</td>
                    <td>{hit.page ?? "—"}</td>
                    <td>{highlight(hit.snippet, hit.matched)}</td>
                    <td>{Math.round(hit.score * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
