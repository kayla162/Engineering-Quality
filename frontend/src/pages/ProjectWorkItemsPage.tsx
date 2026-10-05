import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type { DocumentRole, DocumentSummary, Project, WorkItemList } from "../api/types";
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
  const [onlyMissing, setOnlyMissing] = useState(false);
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

  useEffect(() => {
    void loadProjects();
    api.listDocuments().then((list) => setDocuments(list.items), () => setDocuments([]));
  }, [loadProjects]);

  useEffect(() => {
    if (selectedId) void loadWorkItems(selectedId);
  }, [selectedId, loadWorkItems]);

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

  const selected = projects.find((project) => project.project_id === selectedId) ?? null;

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

            <section className="card">
              <h2>工項清單</h2>
              {workItems && (
                <WorkItemSummary
                  total={workItems.total}
                  withSpecChapter={workItems.with_spec_chapter}
                />
              )}
              <WorkItemTable
                items={workItems?.items ?? []}
                onlyMissing={onlyMissing}
                onOnlyMissingChange={setOnlyMissing}
              />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
