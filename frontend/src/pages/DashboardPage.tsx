import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { Dashboard, RegulationStatus } from "../api/types";
import { RegulationChangesPanel } from "../components/RegulationChangesPanel";
import { StatusBadge } from "../components/StatusBadge";
import { REVIEW_LABELS, SOURCE_LABELS, STATUS_LABELS } from "../labels";

const STATUS_ORDER: RegulationStatus[] = [
  "ACTIVE",
  "AMENDED",
  "REPEALED",
  "POSSIBLE_MATCH",
  "NOT_FOUND",
  "UNKNOWN",
];

function Cell({ value, label, tone }: { value: number; label: string; tone?: string }) {
  return (
    <div className={tone ? `summary-cell summary-${tone}` : "summary-cell"}>
      <span className="summary-value">{value}</span>
      <span className="summary-label">{label}</span>
    </div>
  );
}

/** 租戶總覽：數字全部來自既有清單的彙總，和各清單畫面一致。 */
export function DashboardPage({
  canCheckChanges,
  onOpenDocument,
}: {
  canCheckChanges: boolean;
  onOpenDocument: (documentId: string) => void;
}) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.getDashboard());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入總覽");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  if (error) return <section className="card"><p className="error">{error}</p></section>;
  if (!data) return <section className="card"><p className="hint">載入中…</p></section>;

  const mockCount = data.references.by_source.mock ?? 0;

  return (
    <div className="dashboard">
      <section className="card">
        <h2>總覽</h2>
        <div className="summary">
          <Cell value={data.documents.total} label="文件" />
          <Cell value={data.references.total} label="法規引用" />
          <Cell value={data.references.needs_action} label="待處理引用" tone={data.references.needs_action > 0 ? "amended" : undefined} />
          <Cell value={data.open_regulation_changes} label="待確認法規異動" tone={data.open_regulation_changes > 0 ? "repealed" : undefined} />
          <Cell value={data.projects} label="專案" />
        </div>
        <p className="hint">「待處理引用」= 狀態需要人工確認（已修正、已廢止、疑似、查無、查詢失敗），且還沒有人覆核。</p>
        {(data.documents.degraded > 0 || data.documents.failed > 0) && (
          <p className="error">
            {data.documents.degraded > 0 && `${data.documents.degraded} 份文件解析品質不佳（圖頁或 OCR 頁偏多），結果可能不完整。`}
            {data.documents.failed > 0 && `${data.documents.failed} 份文件分析失敗。`}
          </p>
        )}
      </section>

      <section className="card">
        <h2>引用狀態</h2>
        <div className="summary">
          {STATUS_ORDER.map((status) => (
            <Cell key={status} value={data.references.by_status[status] ?? 0} label={STATUS_LABELS[status]} tone={status.toLowerCase()} />
          ))}
        </div>
        <div className="summary">
          {(["UNREVIEWED", "CONFIRMED", "REJECTED"] as const).map((status) => (
            <Cell key={status} value={data.references.by_review[status] ?? 0} label={REVIEW_LABELS[status]} />
          ))}
        </div>
        <h3>資料來源</h3>
        {Object.keys(data.references.by_source).length === 0 ? (
          <p className="hint">還沒有比對到任何法規。</p>
        ) : (
          <ul>
            {Object.entries(data.references.by_source).map(([source, count]) => (
              <li key={source}>{SOURCE_LABELS[source] ?? source}：{count} 筆</li>
            ))}
          </ul>
        )}
        {mockCount > 0 && (
          <p className="error">有 {mockCount} 筆引用比對到假資料，不可作為查核依據，請接上官方資料來源後重新分析。</p>
        )}
      </section>

      <RegulationChangesPanel canCheck={canCheckChanges} onOpenDocument={onOpenDocument} onChanged={() => void refresh()} />

      <section className="card">
        <h2>待處理最多的文件</h2>
        {data.documents_needing_action.length === 0 ? (
          <p className="hint">沒有待處理的引用。</p>
        ) : (
          <table>
            <thead>
              <tr><th>文件</th><th>待處理</th><th>未覆核</th><th>引用總數</th></tr>
            </thead>
            <tbody>
              {data.documents_needing_action.map((doc) => (
                <tr key={doc.document_id} className="clickable" onClick={() => onOpenDocument(doc.document_id)}>
                  <td>
                    {doc.filename}
                    {doc.parse_quality === "DEGRADED" && <span className="hint">（解析品質不佳）</span>}
                  </td>
                  <td>{doc.needs_action}</td>
                  <td>{doc.unreviewed}</td>
                  <td>{doc.references}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>最常引用的法規</h2>
        {data.top_regulations.length === 0 ? (
          <p className="hint">還沒有比對到任何法規。</p>
        ) : (
          <table>
            <thead>
              <tr><th>法規</th><th>狀態</th><th>來源</th><th>引用次數</th><th>文件數</th></tr>
            </thead>
            <tbody>
              {data.top_regulations.map((row) => (
                <tr key={row.regulation_id}>
                  <td>{row.name}</td>
                  <td><StatusBadge status={row.status} /></td>
                  <td>{SOURCE_LABELS[row.source] ?? row.source}</td>
                  <td>{row.references}</td>
                  <td>{row.documents}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
