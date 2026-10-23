import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { AuditLogItem } from "../api/types";
import { AUDIT_ACTION_LABELS, formatDateTime } from "../labels";

const PAGE_SIZE = 50;

/** 把 detail 轉成一行看得懂的字。只挑常見欄位，其餘照原樣列出。 */
function describe(item: AuditLogItem): string {
  const detail = item.detail ?? {};
  const parts: string[] = [];
  for (const key of ["filename", "name", "username", "raw_text", "review_status", "review_note", "format", "role", "reason"]) {
    const value = detail[key];
    if (value !== undefined && value !== null && value !== "") parts.push(String(value));
  }
  for (const key of ["checked", "changed", "skipped", "total"]) {
    if (typeof detail[key] === "number") parts.push(`${key}=${detail[key]}`);
  }
  return parts.join(" · ");
}

/** 租戶管理員查看同租戶的操作紀錄。紀錄只能看，不能改也不能刪。 */
export function AuditLogPanel() {
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const body = await api.listAuditLogs({ action, username: username.trim() }, page, PAGE_SIZE);
      setItems(body.items);
      setTotal(body.total);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入稽核紀錄");
    }
  }, [action, username, page]);

  useEffect(() => { void refresh(); }, [refresh]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="card">
      <h2>稽核紀錄</h2>
      <p className="hint">誰在何時做了什麼。只記錄成功的寫入、匯出與登入事件；查詢不記錄。</p>
      <div className="filters">
        <label>
          操作
          <select value={action} onChange={(event) => { setPage(1); setAction(event.target.value); }}>
            <option value="">全部</option>
            {Object.entries(AUDIT_ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          使用者
          <input value={username} onChange={(event) => { setPage(1); setUsername(event.target.value); }} placeholder="登入名稱" />
        </label>
      </div>

      {items.length === 0 ? (
        <p className="hint">沒有符合條件的紀錄。</p>
      ) : (
        <table>
          <thead>
            <tr><th>時間</th><th>使用者</th><th>操作</th><th>內容</th><th>IP</th></tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.audit_id} className={item.action === "login_failed" ? "attention" : undefined}>
                <td className="nowrap">{formatDateTime(item.created_at)}</td>
                <td>{item.username}</td>
                <td>{AUDIT_ACTION_LABELS[item.action] ?? item.action}</td>
                <td>{describe(item)}</td>
                <td>{item.ip_address ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="row">
        <span className="hint">共 {total} 筆，第 {page} / {pages} 頁</span>
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一頁</button>
        <button type="button" className="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一頁</button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
