import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  Checklist,
  DocumentRole,
  DocumentSummary,
  Project,
  WorkItemList,
} from "../api/types";
import {
  ChecklistSummary,
  ChecklistTable,
  type ChecklistResultFilter,
} from "../components/ChecklistTable";
import { ProjectPanel } from "../components/ProjectPanel";
import { WorkItemSummary, WorkItemTable } from "../components/WorkItemTable";

const ROLE_LABELS: Record<DocumentRole, string> = {
  boq: "標單（詳細價目表）",
  contract: "契約書",
  drawing: "契約圖",
  specification: "施工規範",
  other: "其他",
};

export function ProjectWorkItemsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [workItems, setWorkItems] = useState<WorkItemList | null>(null);
  // 檢核表依專案分開存：切換專案後，上一個專案的列不能留在新專案的標題底下；
  // 重建要花好幾秒，慢回來的舊專案回應也只能存進舊專案自己名下，不能蓋掉新專案的畫面。
  const [checklists, setChecklists] = useState<Record<string, Checklist>>({});
  const [resultFilter, setResultFilter] = useState<ChecklistResultFilter>("ALL");
  const [buildingChecklist, setBuildingChecklist] = useState(false);
  const [onlyMissing, setOnlyMissing] = useState(false);
  // 工項清單預設收合。篩選（onlyMissing）與資料都存在這一層，收合只是不畫，不會被重設。
  const [workItemsOpen, setWorkItemsOpen] = useState(false);
  const [documentId, setDocumentId] = useState("");
  const [role, setRole] = useState<DocumentRole>("boq");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function report(err: unknown, fallback: string) {
    setError(err instanceof ApiError ? err.message : fallback);
  }

  const loadProjects = useCallback(async () => {
    try {
      setProjects((await api.listProjects()).items);
    } catch (err) {
      report(err, "無法載入專案清單");
    }
  }, []);

  const loadWorkItems = useCallback(async (projectId: string) => {
    try {
      setWorkItems(await api.listWorkItems(projectId));
    } catch (err) {
      report(err, "無法載入工項清單");
    }
  }, []);

  const loadChecklist = useCallback(async (projectId: string) => {
    try {
      const data = await api.getChecklist(projectId);
      setChecklists((previous) => ({ ...previous, [projectId]: data }));
    } catch (err) {
      report(err, "無法載入檢核表");
    }
  }, []);

  useEffect(() => {
    void loadProjects();
    api.listDocuments().then((list) => setDocuments(list.items), () => setDocuments([]));
  }, [loadProjects]);

  useEffect(() => {
    if (selectedId) {
      void loadWorkItems(selectedId);
      void loadChecklist(selectedId);
    }
  }, [selectedId, loadWorkItems, loadChecklist]);

  async function createProject(name: string) {
    setError(null);
    try {
      const project = await api.createProject(name);
      await loadProjects();
      setSelectedId(project.project_id);
    } catch (err) {
      report(err, "無法建立專案");
    }
  }

  async function attach() {
    if (!selectedId || documentId === "") return;
    setError(null);
    setBusy(true);
    try {
      await api.attachDocument(selectedId, documentId, role);
      setDocumentId("");
    } catch (err) {
      report(err, "無法把文件掛到專案");
    } finally {
      setBusy(false);
    }
  }

  async function build() {
    if (!selectedId) return;
    setError(null);
    setBusy(true);
    try {
      setWorkItems(await api.buildWorkItems(selectedId));
    } catch (err) {
      report(err, "無法建立工項清單");
    } finally {
      setBusy(false);
    }
  }

  async function buildChecklist() {
    if (!selectedId) return;
    const projectId = selectedId;
    setError(null);
    setBusy(true);
    setBuildingChecklist(true);
    try {
      const data = await api.buildChecklist(projectId);
      setChecklists((previous) => ({ ...previous, [projectId]: data }));
    } catch (err) {
      report(err, "無法建立檢核表");
    } finally {
      setBusy(false);
      setBuildingChecklist(false);
    }
  }

  const selected = projects.find((project) => project.project_id === selectedId) ?? null;

  const checklist = selectedId === null ? null : (checklists[selectedId] ?? null);

  return (
    <div className="layout">
      <div className="sidebar">
        <ProjectPanel
          projects={projects}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onCreate={(name) => void createProject(name)}
        />
        {error && <p className="error">{error}</p>}
      </div>

      <main>
        {selected === null ? (
          <section className="card">
            <h2>請先選擇或建立一個專案</h2>
            <p className="hint">
              專案是加在文件之上的一層：同一份文件照常走上傳與分析，專案只記錄
              「這份文件在這個專案裡扮演什麼角色」。工項清單來自角色為「標單」的那份文件。
            </p>
          </section>
        ) : (
          <>
            <section className="card">
              <h2>{selected.name}</h2>

              <div className="field">
                <label htmlFor="attach-document">掛上文件</label>
                <select
                  id="attach-document"
                  value={documentId}
                  onChange={(event) => setDocumentId(event.target.value)}
                >
                  <option value="">選擇已上傳的文件…</option>
                  {documents.map((document) => (
                    <option key={document.document_id} value={document.document_id}>
                      {document.filename}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="文件角色"
                  value={role}
                  onChange={(event) => setRole(event.target.value as DocumentRole)}
                >
                  {Object.entries(ROLE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <button type="button" disabled={busy || documentId === ""} onClick={() => void attach()}>
                  掛上去
                </button>
              </div>

              <div className="field">
                <button type="button" disabled={busy} onClick={() => void build()}>
                  從標單建立工項
                </button>
                {/* 重跑是取代不是累加，講清楚才不會有人以為會變兩倍 */}
                <span className="hint">重新建立會取代現有的工項清單，不會累加。</span>
              </div>
            </section>

            {/*
              區塊順序：先是收合的工項清單（只佔一條），然後是檢核表。
              兩張表各一千多列，排在後面的那張表前面不能有另一張攤開的表，不然它的標題
              就在十幾萬像素以外，等於找不到。檢核表有項次與名稱，多數時候看它就夠了，所以它
              預設展開、緊接在這一條後面；工項清單要看再展開。
              （實測：檢核表在上、工項清單收合在下時，工項清單的標題仍在十一萬像素以外——
              收合排在後面的區塊，救不了它自己的標題。）
            */}
            <section className="card">
              <div className="row">
                <h2>工項清單</h2>
                <button
                  type="button"
                  className="secondary"
                  aria-expanded={workItemsOpen}
                  onClick={() => setWorkItemsOpen((open) => !open)}
                >
                  {workItemsOpen
                    ? "收合工項清單"
                    : `展開工項清單${workItems ? `（共 ${workItems.total} 筆）` : ""}`}
                </button>
              </div>
              {/*
                收合時整張表不掛載：一千多列的表放在頁面上，排在它後面的區塊就捲不到了。
                資料還沒載入時也不畫，不然 WorkItemTable 會對一個只是還沒載入的專案說「還沒有工項」。
              */}
              {workItemsOpen && workItems && (
                <>
                  <WorkItemSummary
                    total={workItems.total}
                    withSpecChapter={workItems.with_spec_chapter}
                  />
                  <WorkItemTable
                    items={workItems.items}
                    onlyMissing={onlyMissing}
                    onOnlyMissingChange={setOnlyMissing}
                  />
                </>
              )}
            </section>

            <section className="card">
              <h2>檢核表</h2>

              <div className="field">
                <button type="button" disabled={busy} onClick={() => void buildChecklist()}>
                  {buildingChecklist ? "建立中…" : "建立檢核表"}
                </button>
                {/* 依據來自規範書；重跑是取代不是累加，也要講清楚 */}
                <span className="hint">
                  依據來自角色為「施工規範」的文件。重新建立會重讀規範書並取代現有的依據，不會累加。
                </span>
              </div>

              {/*
                還沒載入完成（或載入失敗）時什麼都不畫：這時畫出 ChecklistTable，
                它會說「這個專案還沒有可檢核的工項」——對一個只是還沒載入的專案是錯的。
                載入失敗由側欄的錯誤訊息交代。
              */}
              {checklist && (
                <>
                  {checklist.total > 0 && (
                    <>
                      <ChecklistSummary
                        ok={checklist.summary.ok}
                        specNotIncluded={checklist.summary.spec_not_included}
                        needsConfirmation={checklist.summary.needs_confirmation}
                      />
                      {/* 規範書解析品質不佳時依據可能殘缺，使用者必須在看到表之前就知道 */}
                      {checklist.spec_warning && <p className="error">{checklist.spec_warning}</p>}
                      {/* 契約是專案層級的依據、不逐工項列：這句話不顯示，就沒有人知道契約欄去哪了 */}
                      <p className="hint">{checklist.contract_note}</p>
                    </>
                  )}
                  <ChecklistTable
                    items={checklist.items}
                    resultFilter={resultFilter}
                    onResultFilterChange={setResultFilter}
                  />
                </>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
