import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Job, ReferenceFilters, ReferenceList } from "../api/types";
import { FilterBar } from "../components/FilterBar";
import { JobProgress } from "../components/JobProgress";
import { ReferenceDetailPanel } from "../components/ReferenceDetailPanel";
import { ReferenceTable, SummaryBar } from "../components/ReferenceTable";

const POLL_INTERVAL_MS = 1000;

export function DocumentAnalysisPage({
  documentId,
  filename,
  onDocumentChanged,
}: {
  documentId: string;
  filename: string;
  onDocumentChanged: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [references, setReferences] = useState<ReferenceList | null>(null);
  const [filters, setFilters] = useState<ReferenceFilters>({});
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const loadReferences = useCallback(async () => {
    try {
      setReferences(await api.listReferences(documentId, filters));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "載入清單失敗");
    }
  }, [documentId, filters]);

  // 切換文件時重置狀態
  useEffect(() => {
    setJob(null);
    setReferences(null);
    setSelectedReference(null);
    setError(null);
    void loadReferences();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  useEffect(() => {
    void loadReferences();
  }, [loadReferences]);

  // 分析進行中就持續輪詢，完成後重新載入清單
  useEffect(() => {
    if (!job || job.status === "COMPLETED" || job.status === "FAILED") return;
    const timer = setTimeout(async () => {
      try {
        const next = await api.getJob(job.job_id);
        setJob(next);
        if (next.status === "COMPLETED") {
          await loadReferences();
          onDocumentChanged();
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "查詢進度失敗");
      }
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [job, loadReferences, onDocumentChanged]);

  async function startAnalysis() {
    setStarting(true);
    setError(null);
    try {
      const created = await api.startAnalysis(documentId);
      setJob(await api.getJob(created.job_id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法開始分析");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="analysis">
      <section className="card">
        <div className="row">
          <h2>{filename}</h2>
          <div className="actions">
            <button type="button" disabled={starting} onClick={() => void startAnalysis()}>
              {references && references.total > 0 ? "重新分析" : "開始分析"}
            </button>
            {(["xlsx", "csv", "pdf"] as const).map((format) => (
              <a
                key={format}
                className="button secondary"
                href={api.exportReportUrl(documentId, format)}
              >
                匯出 {format.toUpperCase()}
              </a>
            ))}
          </div>
        </div>
        {job && <JobProgress job={job} />}
        {error && <p className="error">{error}</p>}
        {references && <SummaryBar summary={references.summary} />}
      </section>

      <div className="analysis-body">
        <section className="card">
          <div className="row">
            <h2>法規引用清單{references ? `（${references.total}）` : ""}</h2>
          </div>
          <FilterBar filters={filters} onChange={setFilters} />
          {references ? (
            <ReferenceTable
              items={references.items}
              selectedId={selectedReference}
              onSelect={setSelectedReference}
            />
          ) : (
            <p className="hint">載入中…</p>
          )}
        </section>

        {selectedReference && (
          <ReferenceDetailPanel
            referenceId={selectedReference}
            onReviewed={() => void loadReferences()}
          />
        )}
      </div>
    </div>
  );
}
