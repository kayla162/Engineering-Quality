import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ReferenceDetail, ReviewStatus } from "../api/types";
import {
  AI_PURPOSE_LABELS,
  METHOD_LABELS,
  TYPE_LABELS,
  formatDateTime,
  formatPercent,
} from "../labels";
import { ReviewBadge, StatusBadge } from "./StatusBadge";

export function ReferenceDetailPanel({
  referenceId,
  onReviewed,
}: {
  referenceId: string;
  onReviewed: () => void;
}) {
  const [detail, setDetail] = useState<ReferenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    api
      .getReference(referenceId)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        setNote(data.review_note ?? "");
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "載入失敗"));
    return () => {
      cancelled = true;
    };
  }, [referenceId]);

  async function submitReview(status: ReviewStatus) {
    setSaving(true);
    setError(null);
    try {
      setDetail(
        await api.reviewReference(referenceId, {
          review_status: status,
          review_note: note.trim() || undefined,
        }),
      );
      onReviewed();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "覆核失敗");
    } finally {
      setSaving(false);
    }
  }

  if (error && !detail) return <aside className="card detail"><p className="error">{error}</p></aside>;
  if (!detail) return <aside className="card detail"><p className="hint">載入中…</p></aside>;

  return (
    <aside className="card detail">
      <h2>詳細資訊</h2>

      <h3>文件中的引用</h3>
      <dl>
        <dt>原始文字</dt>
        <dd>{detail.raw_text}</dd>
        <dt>正規化名稱</dt>
        <dd>{detail.normalized_name ?? "—"}</dd>
        <dt>類型</dt>
        <dd>{TYPE_LABELS[detail.regulation_type] ?? detail.regulation_type}</dd>
        <dt>條號 / 標準編號</dt>
        <dd>{detail.article ?? detail.standard_number ?? "—"}</dd>
        <dt>來源文件</dt>
        <dd>
          {detail.source_document}
          {detail.page !== null ? `（第 ${detail.page} 頁）` : ""}
        </dd>
        <dt>抽取方式</dt>
        <dd>
          {METHOD_LABELS[detail.extraction_method] ?? detail.extraction_method}（信心{" "}
          {formatPercent(detail.extraction_confidence)}）
        </dd>
      </dl>
      {detail.section_text && <blockquote>{detail.section_text}</blockquote>}

      <h3>比對結果</h3>
      <p>
        <StatusBadge status={detail.status} tentative={detail.is_tentative} />{" "}
        信心 {formatPercent(detail.match_confidence)}
      </p>
      {detail.matched_regulation ? (
        <dl>
          <dt>官方名稱</dt>
          <dd>{detail.matched_regulation.name}</dd>
          <dt>發布機關</dt>
          <dd>{detail.matched_regulation.authority ?? "—"}</dd>
          <dt>生效 / 最近修正</dt>
          <dd>
            {detail.matched_regulation.effective_date ?? "—"} /{" "}
            {detail.matched_regulation.last_amended_date ?? "—"}
          </dd>
          <dt>資料來源</dt>
          <dd>
            <span className="badge source">{detail.matched_regulation.source}</span>
            {detail.matched_regulation.source === "mock" && (
              <span className="hint"> 假資料，僅供 Demo，務必人工查證</span>
            )}
          </dd>
          <dt>官方連結</dt>
          <dd>
            {detail.matched_regulation.official_url ? (
              <a href={detail.matched_regulation.official_url} target="_blank" rel="noreferrer">
                開啟
              </a>
            ) : (
              "—"
            )}
          </dd>
        </dl>
      ) : (
        <p className="hint">沒有比對到任何法規。</p>
      )}

      <h3>比對理由</h3>
      <ul>
        {detail.match_reasons.length > 0 ? (
          detail.match_reasons.map((reason, index) => <li key={index}>{reason}</li>)
        ) : (
          <li className="hint">—</li>
        )}
      </ul>

      <h3>查詢紀錄</h3>
      {detail.query_history.length > 0 ? (
        <ul>
          {detail.query_history.map((row, index) => (
            <li key={index}>
              {row.source}｜{formatDateTime(row.queried_at)}｜HTTP {row.http_status ?? "—"}｜
              {row.latency_ms ?? "—"} ms
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">這筆使用了資料庫中既有的法規資料，本次沒有再查詢外部來源。</p>
      )}

      <h3>AI 使用情形</h3>
      {detail.ai_invocations.length > 0 ? (
        <ul>
          {detail.ai_invocations.map((row, index) => (
            <li key={index}>
              {AI_PURPOSE_LABELS[row.purpose] ?? row.purpose}｜{row.model}｜{row.prompt_version}｜
              信心 {formatPercent(row.confidence)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">這筆判斷完全沒有使用 AI。</p>
      )}

      <h3>人工覆核</h3>
      <p>
        目前狀態：<ReviewBadge status={detail.review_status} />
        {detail.reviewed_by && (
          <span className="hint">
            {" "}
            由 {detail.reviewed_by} 於 {formatDateTime(detail.reviewed_at)}
          </span>
        )}
      </p>
      <label>
        備註
        <textarea value={note} rows={2} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="actions">
        <button type="button" disabled={saving} onClick={() => void submitReview("CONFIRMED")}>
          確認判斷正確
        </button>
        <button
          type="button"
          className="secondary"
          disabled={saving}
          onClick={() => void submitReview("REJECTED")}
        >
          判定為錯誤
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <p className="hint">人工覆核不會改變系統的判斷結果，兩者各自獨立記錄。</p>
    </aside>
  );
}
