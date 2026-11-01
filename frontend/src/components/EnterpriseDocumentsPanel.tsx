import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import type { EnterpriseDocumentList } from "../api/types";
import { formatDateTime } from "../labels";
import { StatusBadge } from "./StatusBadge";

interface RowError {
  row: number | null;
  message: string;
}

/** 企業內部文件清單。成員可以看；租戶管理員可以下載範本、匯入（整份取代）。 */
export function EnterpriseDocumentsPanel({
  canImport,
  onImported,
}: {
  canImport: boolean;
  onImported: () => void;
}) {
  const [data, setData] = useState<EnterpriseDocumentList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<RowError[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.listEnterpriseDocuments());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入企業內部文件");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function importFile(file: File) {
    setBusy(true);
    setError(null);
    setRowErrors([]);
    setNotice(null);
    try {
      const body = await api.importEnterpriseDocuments(file);
      setData(body);
      setNotice(`已匯入 ${body.total} 份文件。已分析過的文件要重新分析才會用上新清單。`);
      onImported();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        if (Array.isArray(err.details)) setRowErrors(err.details as RowError[]);
      } else {
        setError("無法匯入清單");
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <section className="card">
      <div className="row">
        <h2>企業內部文件</h2>
        {canImport && (
          <>
            <a className="button secondary" href={api.enterpriseTemplateUrl}>下載範本</a>
            <label className="button">
              {busy ? "匯入中…" : "匯入清單"}
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx"
                hidden
                disabled={busy}
                aria-label="匯入企業內部文件清單"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void importFile(file);
                }}
              />
            </label>
          </>
        )}
      </div>
      <p className="hint">
        公司的品質手冊、程序書、作業標準等內部文件。匯入後，工程文件裡用名稱、別名或文件編號引用的內部文件，都會比對現行或作廢狀態。匯入會整份取代舊清單。
      </p>

      {notice && <p className="success" role="status">{notice}</p>}
      {error && <p className="error">{error}</p>}
      {rowErrors.length > 0 && (
        <ul className="error">
          {rowErrors.map((item, index) => (
            <li key={index}>{item.row ? `第 ${item.row} 列：` : ""}{item.message}</li>
          ))}
        </ul>
      )}

      {data && data.total === 0 ? (
        <p className="hint">
          還沒有匯入清單，內部文件的引用目前抽不到，或會是「查無此法規」。
          {canImport ? "請下載範本給品保／文管單位填寫後匯入。" : "請租戶管理員匯入。"}
        </p>
      ) : data ? (
        <>
          <p className="hint">
            共 {data.total} 份，{formatDateTime(data.imported_at)} 由 {data.imported_by} 匯入。
          </p>
          <table>
            <thead>
              <tr><th>編號</th><th>名稱</th><th>類型</th><th>版次</th><th>生效日</th><th>狀態</th><th>主管單位</th></tr>
            </thead>
            <tbody>
              {data.items.map((doc) => (
                <tr key={doc.document_id}>
                  <td className="nowrap">{doc.doc_number}</td>
                  <td>
                    {doc.name}
                    {doc.replaced_by && <span className="hint">（已由 {doc.replaced_by} 取代）</span>}
                  </td>
                  <td>{doc.doc_type}</td>
                  <td>{doc.revision}</td>
                  <td className="nowrap">{doc.effective_date}</td>
                  <td><StatusBadge status={doc.status} /></td>
                  <td>{doc.owner ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </section>
  );
}
