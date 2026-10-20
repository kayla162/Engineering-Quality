import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DrawingInspection, IntegratedChecklist, IntegratedItem } from "../api/integratedTypes";

const sourceLabels: Record<string, string> = {
  both: "已確認配對", needs_confirmation: "標單工項・圖說待核對",
  drawing_only: "人工確認圖說獨有", drawing_candidate: "圖說候選・待覆核",
};
const basisLabels: Record<string, string> = {
  OK: "已找到規範依據", SPEC_NOT_INCLUDED: "本案規範未收錄", NEEDS_CONFIRMATION: "請確認依據",
};
const reviewLabels: Record<string, string> = {
  pending: "待覆核", confirmed: "已確認", rejected: "已排除", stale: "已過期，待重新核對",
};
const verificationLabels: Record<string, string> = { ACTIVE: "現行有效", AMENDED: "已修正", REPEALED: "已廢止" };
const findingPriority: Record<string, number> = { high: 0, medium: 1, info: 2 };
const PAGE_SIZE = 50;

function Evidence({ item, projectId }: { item: IntegratedItem; projectId: string }) {
  return <details className="integrated-evidence"><summary>證據與工法候選</summary>
    {item.drawings.map(d => <div className="integrated-source" key={d.id}>
      <a href={api.drawingFileUrl(projectId, d.document_id, d.page)} target="_blank" rel="noreferrer">
        {d.number ?? "無圖號"} · 第 {d.page} 頁
      </a>
      <span className="hint">　{d.filename} · {reviewLabels[d.review_status] ?? d.review_status}</span>
      {d.review_note && <p>{d.review_note}</p>}
      <pre>{d.evidence}</pre>
      {d.warning && <p className="hint">{d.warning}</p>}
    </div>)}
    {item.method.candidates.length > 0 && <div className="integrated-method">
      <strong>工法文字候選，尚未選定</strong>
      {item.method.candidates.map((c, i) => <blockquote key={i}><b>{c.text}</b><p>{c.evidence}</p><small>{c.source}</small></blockquote>)}
    </div>}
    {item.drawings.length === 0 && <p className="hint">尚無已確認的圖項連結，請由圖說檢核核對。</p>}
  </details>;
}

export function IntegratedWorkspace({ projectId, refreshVersion = 0 }: { projectId: string; refreshVersion?: number }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"table" | "inspection">("table");
  const [data, setData] = useState<IntegratedChecklist | null>(null);
  const [inspection, setInspection] = useState<DrawingInspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [basis, setBasis] = useState("");
  const [method, setMethod] = useState("");
  const [page, setPage] = useState(0);
  const [groupPage, setGroupPage] = useState(0);
  const [findingPage, setFindingPage] = useState(0);

  useEffect(() => { setData(null); setInspection(null); setQuery(""); setPage(0); setGroupPage(0); setFindingPage(0); }, [projectId]);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoading(true); setError(null);
    const load = async () => {
      try {
        if (mode === "table") {
          const result = await api.getIntegratedChecklist(projectId);
          if (current) setData(result);
        } else {
          const result = await api.getDrawingInspection(projectId);
          if (current) setInspection(result);
        }
      } catch (err) {
        if (current) { setData(null); setInspection(null); setError(err instanceof Error ? err.message : "無法載入整合資料"); }
      } finally { if (current) setLoading(false); }
    };
    void load();
    return () => { current = false; };
  }, [projectId, open, mode, refreshVersion, reload]);
  useEffect(() => { setPage(0); setGroupPage(0); setFindingPage(0); }, [query, source, basis, method]);

  const visibleData = data?.project_id === projectId ? data : null;
  const visibleInspection = inspection?.project_id === projectId ? inspection : null;
  const rows = useMemo(() => (visibleData?.items ?? []).filter(item => {
    const text = [item.name, item.item_no, item.chapter_code,
      ...item.drawings.flatMap(d => [d.number, d.title, d.evidence, d.review_note]),
      ...item.bases.map(b => b.reference), ...item.method.candidates.map(c => c.text)].join(" ").toLocaleLowerCase();
    return text.includes(query.toLocaleLowerCase()) && (!source || item.source_status === source)
      && (!basis || (basis === "none" ? item.basis_result === null : item.basis_result === basis))
      && (!method || item.method.status === method);
  }), [visibleData, query, source, basis, method]);
  const groups = (visibleInspection?.groups ?? []).filter(g =>
    `${g.names.join(" ")} ${g.items.map(i => `${i.number} ${i.review_note}`).join(" ")}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const findings = (visibleInspection?.findings ?? []).filter(f =>
    `${f.title} ${f.message} ${f.quote} ${f.source_number}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => (findingPriority[a.priority] ?? 3) - (findingPriority[b.priority] ?? 3));
  useEffect(() => {
    setPage(value => Math.min(value, Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1)));
  }, [rows.length]);
  useEffect(() => {
    setGroupPage(value => Math.min(value, Math.max(0, Math.ceil(groups.length / PAGE_SIZE) - 1)));
  }, [groups.length]);
  useEffect(() => {
    setFindingPage(value => Math.min(value, Math.max(0, Math.ceil(findings.length / PAGE_SIZE) - 1)));
  }, [findings.length]);
  const warnings = mode === "table" ? visibleData?.warnings : visibleInspection?.warnings;
  const pager = (value: number, count: number, change: (n: number) => void, label: string) => <div className="integrated-pager">
    <span>{count === 0 ? 0 : Math.min(value * PAGE_SIZE + 1, count)}–{Math.min((value + 1) * PAGE_SIZE, count)}／{count} 筆</span>
    <button type="button" className="secondary" disabled={value === 0} onClick={() => change(value - 1)} aria-label={`${label}上一頁`}>上一頁</button>
    <button type="button" className="secondary" disabled={(value + 1) * PAGE_SIZE >= count} onClick={() => change(value + 1)} aria-label={`${label}下一頁`}>下一頁</button>
  </div>;

  return <section className="card integrated-workspace">
    <div className="row"><div><h2>整合檢核工作區</h2><p className="hint">圖說、規範依據與工法線索一起查閱；人工標註保留。</p></div>
      <button type="button" className="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "收合整合檢核" : "展開整合檢核"}</button></div>
    {open && <>
      <div className="integrated-toolbar">
        <div className="actions">
          <button type="button" className={mode === "table" ? "" : "secondary"} aria-pressed={mode === "table"} onClick={() => setMode("table")}>整合工項與工法</button>
          <button type="button" className={mode === "inspection" ? "" : "secondary"} aria-pressed={mode === "inspection"} onClick={() => setMode("inspection")}>名稱分組與核對疑義</button>
        </div>
        <button type="button" className="secondary" disabled={loading} onClick={() => setReload(n => n + 1)}>重新讀取資料</button>
      </div>
      {loading && <p role="status">載入中…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {warnings && warnings.length > 0 && <details className="integrated-notes" open><summary>資料範圍與待確認事項</summary>{warnings.map((w, i) => <p key={i}>{w}</p>)}</details>}
      <div className="filters">
        <label className="integrated-search">搜尋整合工項<input value={query} onChange={e => setQuery(e.target.value)} placeholder="工項、圖號、原文或註記" /></label>
        {mode === "table" && <>
          <label>圖說配對<select value={source} onChange={e => setSource(e.target.value)}><option value="">全部</option>{Object.entries(sourceLabels).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>規範依據<select value={basis} onChange={e => setBasis(e.target.value)}><option value="">全部</option><option value="none">尚無依據</option>{Object.entries(basisLabels).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>工法<select value={method} onChange={e => setMethod(e.target.value)}><option value="">全部</option><option value="pending">有待核對文字候選</option><option value="unspecified">未指定</option></select></label>
        </>}
      </div>
      {mode === "table" && visibleData && <>
        <div className="integrated-overview"><span><strong>{visibleData.total.toLocaleString()}</strong> 聯集列</span>
          <span>{visibleData.summary.work_items ?? 0} 標單工項</span><span>{visibleData.summary.pending_items ?? 0} 待覆核圖項</span>
          <span className="hint">資料版本 {visibleData.revision}</span></div>
        <p className="hint">{visibleData.contract_note}</p>
        <div className="row"><p className="hint">規範依據已找到不代表全面合規；工法文字候選尚未經人員選定。</p>
          <div className="actions">{(["xlsx","csv","pdf"] as const).map(f => <a key={f} className="button secondary" href={api.exportIntegratedUrl(projectId,f)} target="_blank" rel="noreferrer">匯出 {f === "xlsx" ? "Excel" : f.toUpperCase()}</a>)}</div></div>
        <p className="hint">匯出包含全部工項，畫面篩選只影響下方清單。</p>
        {pager(page, rows.length, setPage, "工項")}
        {rows.length === 0 ? <p className="hint">沒有符合條件的資料。</p> : <div className="integrated-scroll"><table>
          <thead><tr><th>工項／項次</th><th>圖說配對</th><th>規範依據</th><th>工法與原圖證據</th></tr></thead>
          <tbody>{rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(item => <tr key={item.key}>
            <td className="integrated-name"><small>{item.item_no ?? "圖說候選"}</small><div>{item.name}</div></td>
            <td><span className="badge source">{sourceLabels[item.source_status] ?? item.source_status}</span><p className="hint">{item.drawings.length} 筆圖項連結</p></td>
            <td><strong>{item.basis_result ? (basisLabels[item.basis_result] ?? item.basis_result) : "尚無依據"}</strong>
              {item.chapter_code && <p>章碼 {item.chapter_code} {item.chapter?.title}</p>}
              {item.bases.length > 0 && <details><summary>{item.bases.length} 條依據</summary>{item.bases.map((b,i) => <p key={i}>{b.reference}<br/><small>{b.detail} · {b.verification_status ? verificationLabels[b.verification_status] ?? b.verification_status : "未查證"}</small></p>)}</details>}</td>
            <td><p className="integrated-method-status">{item.method.status === "pending" ? "未指定・有待核對候選" : "未指定"}</p><Evidence item={item} projectId={projectId}/></td>
          </tr>)}</tbody>
        </table></div>}
      </>}
      {mode === "inspection" && visibleInspection && <>
        <p className="hint">目前資料版本 {visibleInspection.revision}；歷史核對版本 {visibleInspection.historical_revision ?? "未建立"}。下方名稱分組顯示目前人工狀態；疑義與近似提示為歷史整理。</p>
        <div className="integrated-overview"><span><strong>{visibleInspection.summary.current_name_groups}</strong> 名稱分組</span>
          <span>{visibleInspection.summary.index_title_differences} 處圖名差異</span><span>{visibleInspection.summary.references} 筆引用候選</span></div>
        <h3>引用與核對事項</h3>{pager(findingPage,findings.length,setFindingPage,"疑義")}
        {findings.slice(findingPage*PAGE_SIZE,(findingPage+1)*PAGE_SIZE).map(f => <details className="inspection-finding" key={f.id}>
          <summary>{f.source_number ?? ""} {f.title}</summary><p>{f.message}</p>
          {f.quote && <blockquote>{f.quote}</blockquote>}
          {f.document_url && <a href={f.document_url} target="_blank" rel="noreferrer">查看來源第 {f.source_page} 頁</a>}
          {f.targets.map((t,i) => <p className="hint" key={i}>候選目標：{t.number} · 第 {t.page} 頁 · {t.title}</p>)}
        </details>)}
        {!findings.length && <p className="hint">沒有可顯示的歷史疑義；不代表圖面沒有問題。</p>}
        {visibleInspection.similar_hints.length > 0 && <details><summary>近似名稱提示 · {visibleInspection.similar_hints.length} 對</summary>
          {visibleInspection.similar_hints.map((h,i) => <p key={i}>{h.left_name} ／ {h.right_name}<br/><small>{h.reason} · {h.decision}</small></p>)}</details>}
        <h3>目前候選名稱分組</h3><p className="hint">同名不代表同一施工位置；沒有自動合併或更改人工標註。</p>
        {pager(groupPage,groups.length,setGroupPage,"分組")}
        {groups.slice(groupPage*PAGE_SIZE,(groupPage+1)*PAGE_SIZE).map(g => <details key={g.id} className="inspection-group">
          <summary>{g.names.join("／")} · {g.occurrence_count} 筆／{g.page_count} 頁</summary>
          {g.items.map(i => <div key={i.id}><a href={i.document_url} target="_blank" rel="noreferrer">{i.number ?? "無圖號"} · 第 {i.page} 頁</a>　<span>{reviewLabels[i.review_status] ?? i.review_status}</span>{i.review_note && <p>{i.review_note}</p>}</div>)}
        </details>)}
        {visibleInspection.images.length > 0 && <details><summary>核對影像抽樣 · {visibleInspection.images.length} 張</summary><div className="inspection-images">
          {visibleInspection.images.map(i => <a key={i.id} href={i.url} target="_blank" rel="noreferrer">{i.label}</a>)}</div></details>}
      </>}
    </>}
  </section>;
}
