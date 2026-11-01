import { useState, type FormEvent, type ReactNode } from "react";

import { ApiError, api } from "../api/client";
import type { RegulationStatus, SearchResult } from "../api/types";
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

/** 跨文件檢索（示範）：在所有已分析文件的段落與法規名稱裡找。 */
export function SearchPage({ onOpenDocument }: { onOpenDocument: (documentId: string) => void }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.search(query.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法搜尋");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>跨文件搜尋</h2>
      <form className="filters" onSubmit={(event) => void submit(event)}>
        <label>
          關鍵字
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：混凝土澆置、CNS 3090" />
        </label>
        <button type="submit" disabled={busy || !query.trim()}>{busy ? "搜尋中…" : "搜尋"}</button>
      </form>
      <p className="hint">
        {result?.method_note ?? "示範檢索：依字詞相似度排序，不是語意模型；換個說法可能就找不到。"}
        只搜尋已分析過的文件。
      </p>
      {error && <p className="error">{error}</p>}

      {result && (
        <>
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
