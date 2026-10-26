import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { ChangeCheckResult, RegulationChange, RegulationStatus } from "../api/types";
import { CHANGE_FIELD_LABELS, STATUS_LABELS, formatDateTime } from "../labels";
import { StatusBadge } from "./StatusBadge";

const PRESENCE_LABELS: Record<string, string> = { found: "查得到", missing: "來源已查不到" };

function formatValue(field: string, value: string | null): string {
  if (value === null) return "—";
  if (field === "status") return STATUS_LABELS[value as RegulationStatus] ?? value;
  if (field === "presence") return PRESENCE_LABELS[value] ?? value;
  return value;
}

/** 法規異動監控。檢查由租戶管理員觸發（或排程跑 scripts/check_regulation_changes.py）。 */
export function RegulationChangesPanel({
  canCheck,
  onOpenDocument,
  onChanged,
}: {
  canCheck: boolean;
  onOpenDocument: (documentId: string) => void;
  onChanged: () => void;
}) {
  const [changes, setChanges] = useState<RegulationChange[]>([]);
  const [lastCheck, setLastCheck] = useState<ChangeCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setChanges((await api.listRegulationChanges()).items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入法規異動");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function check() {
    setBusy(true);
    setError(null);
    try {
      setLastCheck(await api.checkRegulationChanges());
      await refresh();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法檢查法規異動");
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge(change: RegulationChange) {
    setError(null);
    try {
      await api.acknowledgeRegulationChange(change.change_id);
      await refresh();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法確認異動");
    }
  }

  return (
    <section className="card">
      <div className="row">
        <h2>法規異動</h2>
        {canCheck && (
          <button type="button" disabled={busy} onClick={() => void check()}>
            {busy ? "檢查中…" : "立即檢查"}
          </button>
        )}
      </div>
      <p className="hint">
        重新查詢文件引用到的法規，比對狀態與修正日期。受影響文件的引用狀態不會自動改變，請檢視後重新分析。
      </p>

      {lastCheck && (
        <p className={lastCheck.changed > 0 ? "error" : "success"} role="status">
          已檢查 {lastCheck.checked} 部法規，新異動 {lastCheck.changed} 筆
          {lastCheck.skipped.length > 0 && `，${lastCheck.skipped.length} 部未能檢查`}。
        </p>
      )}
      {lastCheck && lastCheck.skipped.length > 0 && (
        <ul className="hint">
          {lastCheck.skipped.map((row) => (
            <li key={row.regulation_id}>{row.name}：{row.reason}</li>
          ))}
        </ul>
      )}

      {changes.length === 0 ? (
        <p className="hint">目前沒有待確認的法規異動。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>法規</th>
              <th>異動</th>
              <th>受影響文件</th>
              <th>偵測時間</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {changes.map((change) => (
              <tr key={change.change_id}>
                <td>
                  {change.regulation_name}{" "}
                  <StatusBadge status={change.current_status} />
                </td>
                <td>
                  {Object.entries(change.changes).map(([field, diff]) => (
                    <div key={field}>
                      {CHANGE_FIELD_LABELS[field] ?? field}：{formatValue(field, diff.old)} →{" "}
                      <strong>{formatValue(field, diff.new)}</strong>
                    </div>
                  ))}
                </td>
                <td>
                  {change.affected_documents.length === 0
                    ? "—"
                    : change.affected_documents.map((doc) => (
                        <div key={doc.document_id}>
                          <button type="button" className="link" onClick={() => onOpenDocument(doc.document_id)}>
                            {doc.filename}
                          </button>
                          （{doc.references} 筆）
                        </div>
                      ))}
                </td>
                <td className="nowrap">{formatDateTime(change.detected_at)}</td>
                <td>
                  <button type="button" className="secondary" onClick={() => void acknowledge(change)}>
                    已處理
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
