import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DrawingItem, DrawingSnapshot } from "../api/types";

const STATUS: Record<string, string> = {
  pending: "待覆核", stale: "標單已變更，請重新覆核", confirmed: "已確認", rejected: "已排除",
  both: "標單與圖說皆有", needs_confirmation: "尚未找到圖說依據",
  drawing_only: "圖說有，未對應標單（人工確認）", drawing_candidate: "圖說候選，待確認",
};

export function DrawingPanel({ projectId, refreshVersion = 0, onChanged }: {
  projectId: string; refreshVersion?: number; onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const generation = useRef(0);
  const [data, setData] = useState<DrawingSnapshot | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [sheetId, setSheetId] = useState("");
  const [ocr, setOcr] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<DrawingItem | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [name, setName] = useState("");
  const [evidence, setEvidence] = useState("");
  const [number, setNumber] = useState("");
  const [title, setTitle] = useState("");

  function receive(next: DrawingSnapshot) {
    setReview(null);
    setData(next);
    setDocumentId(previous => next.documents.some(d => d.id === previous) ? previous : next.documents[0]?.id ?? "");
    setSheetId(previous => next.sheets.some(s => s.id === previous) ? previous : next.sheets[0]?.id ?? "");
  }
  async function run(action: () => Promise<DrawingSnapshot>, mutation = true) {
    const token = ++generation.current;
    setBusy(true); setError("");
    try {
      const result = await action();
      if (token === generation.current) receive(result);
      // Collapsing or refreshing the panel does not cancel a committed write.
      if (mutation) onChanged?.();
    }
    catch (err) { if (token === generation.current) setError(err instanceof Error ? err.message : "圖說操作失敗"); }
    finally { if (token === generation.current) setBusy(false); }
  }
  useEffect(() => {
    if (!open) return;
    let active = true;
    const token = ++generation.current;
    setData(null); setReview(null);
    setBusy(true);
    api.getDrawings(projectId).then(result => { if (active && token === generation.current) receive(result); },
      err => { if (active && token === generation.current) setError(err instanceof Error ? err.message : "載入失敗"); })
      .finally(() => { if (active && token === generation.current) setBusy(false); });
    return () => { active = false; generation.current++; };
  }, [open, projectId, refreshVersion]);

  const sheet = data?.sheets.find(s => s.id === sheetId);
  useEffect(() => { setNumber(sheet?.number ?? ""); setTitle(sheet?.title ?? ""); }, [sheet]);
  const work = data?.union.filter(w => w.work_item_id) ?? [];

  async function decide(decision: string) {
    if (!review || !data) return;
    await run(() => api.reviewDrawingItem(projectId, review.id, {
      decision, work_item_ids: decision === "confirmed" ? selected : [], note, expected_revision: data.revision,
    }));
    setReview(null);
  }

  return <section className="card drawing-panel">
    <div className="row"><h2>圖說與標單檢核</h2>
      <button type="button" className="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "收合圖說檢核" : "展開圖說檢核"}
      </button>
    </div>
    {open && <>
      <p className="hint">逐頁保留圖號、圖名與來源。圖名提出的工項只作候選，配對需人工核對原圖。</p>
      {error && <p role="alert" className="error">{error}</p>}
      {busy && <p role="status">處理中…掃描圖 OCR 可能需要數分鐘，完成前保留原有索引。</p>}
      {data && <>
        <div className="field">
          <label htmlFor="drawing-document">圖說文件</label>
          <select id="drawing-document" value={documentId} disabled={busy} onChange={e => setDocumentId(e.target.value)}>
            <option value="">選擇已掛到專案的圖說</option>
            {data.documents.map(d => <option key={d.id} value={d.id}>{d.filename}（{d.indexed ? "已索引" : "未索引"}）</option>)}
          </select>
          <label><input type="checkbox" checked={ocr} disabled={busy} onChange={e => setOcr(e.target.checked)} />本機 OCR（掃描圖）</label>
          <button disabled={busy || !documentId} onClick={() => {
            if (data.documents.find(d => d.id === documentId)?.indexed
              && !window.confirm("重新索引會取代這份圖說的人工修正、圖項與覆核結果，是否繼續？")) return;
            setReview(null);
            void run(() => api.indexDrawing(projectId, documentId, ocr, data.revision));
          }}>建立／重建圖說索引</button>
          <button className="secondary" disabled={busy} onClick={() => void run(() => api.getDrawings(projectId), false)}>重新整理</button>
        </div>
        {data.documents.length === 0 && <p>請先在上方把 PDF 掛為「契約圖」。竣工圖亦保留原檔名稱，使用前請確認適用版本。</p>}
        <div className="drawing-stats">
          <span><strong>{data.summary.pages}</strong> 圖頁</span>
          <span><strong>{data.summary.unreadable_pages}</strong> 頁缺圖號／圖名（含封面）</span>
          <span><strong>{data.summary.pending_items}</strong> 項待覆核</span>
          <span><strong>{data.summary.matched}</strong> 筆標單已確認圖說依據</span>
        </div>
        {data.summary.unindexed_documents > 0 && <p className="error">仍有 {data.summary.unindexed_documents} 份圖說未建立索引。</p>}
        {data.summary.work_items === 0 && <p className="hint">尚無同案標單工項。可先核對圖頁與登錄候選，之後再做工項差異檢核。</p>}
        {data.sheets.length > 0 && <>
          <label htmlFor="drawing-sheet">選擇圖頁</label>
          <select id="drawing-sheet" value={sheetId} onChange={e => { setSheetId(e.target.value); setReview(null); }}>
            {data.sheets.map(s => <option key={s.id} value={s.id}>
              {data.documents.find(d => d.id === s.document_id)?.filename} · 第 {s.page} 頁 · {s.number ?? "圖號待補"} {s.title ?? "圖名待補"}
            </option>)}
          </select>
          {sheet && <div className="drawing-evidence">
            <a href={api.drawingFileUrl(projectId, sheet.document_id, sheet.page)} target="_blank" rel="noreferrer">
              查看原圖第 {sheet.page} 頁</a>
            <span className="hint">　來源：{sheet.method === "ocr" ? "本機 OCR，待人工核對" : sheet.method === "assisted" ? "AI 圖框轉錄，待人工核對" : sheet.method === "manual" ? "人工修正" : sheet.method === "text" ? "PDF 文字層" : "未讀取"}</span>
            {sheet.warning && <p className="error">{sheet.method === "assisted" || sheet.method === "manual" ? "原解析警告／校對紀錄：" : ""}{sheet.warning}</p>}
            <details><summary>原始圖框文字</summary><pre>{sheet.evidence || "未讀取到文字"}</pre></details>
            <details><summary>修正圖號／圖名</summary>
              <form className="field" onSubmit={e => { e.preventDefault(); setReview(null);
                void run(() => api.editDrawingSheet(projectId, sheet.id, { number, title, expected_revision: data.revision })); }}>
                <label>圖號<input required maxLength={64} value={number} onChange={e => setNumber(e.target.value)} /></label>
                <label>圖名<input required maxLength={500} value={title} onChange={e => setTitle(e.target.value)} /></label>
                <button disabled={busy || !number.trim() || !title.trim()}>儲存修正並重設本頁覆核</button>
              </form>
            </details>
            <form className="field" onSubmit={e => { e.preventDefault(); void run(() => api.addDrawingItem(projectId, {
              sheet_id: sheet.id, name, evidence, expected_revision: data.revision,
            })); }}>
              <label>補登圖項<input required maxLength={255} value={name} onChange={e => setName(e.target.value)} placeholder="例如：外牆防水" /></label>
              <label>圖面證據<input required maxLength={4000} value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="原圖位置、標註或文字" /></label>
              <button disabled={busy || !name.trim() || !evidence.trim()}>加入待覆核圖項</button>
            </form>
            <div className="drawing-scroll"><table><thead><tr><th>本頁圖項</th><th>證據</th><th>覆核狀態</th><th>操作</th></tr></thead>
              <tbody>{data.items.filter(i => i.sheet_id === sheet.id).map(i => <tr key={i.id}>
                <td>{i.name}</td><td>{i.evidence}</td><td>{STATUS[i.review_status] ?? i.review_status}</td>
                <td><button disabled={busy} onClick={() => { setReview(i); setSelected(i.review_status === "confirmed" ? i.work_item_ids : []); setNote(i.review_note); }} aria-label={`覆核 ${i.name}`}>覆核</button></td>
              </tr>)}</tbody></table></div>
            {data.items.every(i => i.sheet_id !== sheet.id) && <p className="hint">本頁尚無圖項候選，請查看原圖後補登；不代表本頁沒有工項。</p>}
          </div>}
        </>}
        {review && <fieldset className="drawing-review" disabled={busy}><legend>覆核：{review.name}</legend>
          <p className="hint">名稱相近只作提示，可選多筆；不預先勾選候選。</p>
          <div className="drawing-scroll">{work.map(w => <label className="drawing-choice" key={w.work_item_id}>
            <input type="checkbox" checked={selected.includes(w.work_item_id!)} onChange={e => setSelected(
              e.target.checked ? [...selected, w.work_item_id!] : selected.filter(id => id !== w.work_item_id))} />
            {w.item_no} {w.name} {review.suggested_work_item_ids.includes(w.work_item_id!) && "（名稱候選）"}
          </label>)}</div>
          <label>覆核說明<input required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label>
          <div className="field">
            <button disabled={!note.trim() || selected.length === 0} onClick={() => void decide("confirmed")}>確認配對</button>
            <button disabled={!note.trim() || selected.length > 0 || work.length === 0}
              onClick={() => void decide("confirmed")}>確認為圖說獨有</button>
            <button className="secondary" disabled={!note.trim()} onClick={() => void decide("rejected")}>排除此候選</button>
            <button className="secondary" onClick={() => setReview(null)}>取消覆核</button>
          </div>
        </fieldset>}
        <details><summary>查看工項聯集（{data.union.length} 列，包含待確認候選）</summary>
          <div className="field">
            <label>搜尋工項<input value={search} onChange={e => setSearch(e.target.value)} /></label>
            <label>圖說檢核結果<select value={filter} onChange={e => setFilter(e.target.value)}>
              <option value="all">全部</option>
              {["both", "needs_confirmation", "drawing_only", "drawing_candidate"].map(s => <option key={s} value={s}>{STATUS[s]}</option>)}
            </select></label>
          </div>
          <div className="drawing-scroll"><table><thead><tr><th>標單項次</th><th>工項</th><th>圖說檢核</th><th>來源圖頁</th></tr></thead>
            <tbody>{data.union.filter(w => (filter === "all" || w.status === filter)
              && `${w.item_no ?? ""}${w.name}`.includes(search)).map((w, n) => <tr key={`${w.work_item_id ?? "drawing"}-${n}`}>
                <td>{w.item_no ?? "—"}</td><td>{w.name}</td><td>{STATUS[w.status] ?? w.status}</td>
                <td>{w.drawing_item_ids.map(id => {
                  const source = data.sheets.find(s => s.id === data.items.find(i => i.id === id)?.sheet_id);
                  return source && <button key={id} className="secondary" onClick={() => { setSheetId(source.id); setReview(null); }}>
                    {source.number ?? "圖號待補"} · 第 {source.page} 頁</button>;
                })}</td>
              </tr>)}</tbody></table></div>
        </details>
        <p className="hint">{data.disclaimer}</p>
      </>}
    </>}
  </section>;
}
