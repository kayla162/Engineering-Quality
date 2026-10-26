import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "./api/client";
import type { DocumentSummary, SessionUser, SourcesStatus } from "./api/types";
import { AuditLogPanel } from "./components/AuditLogPanel";
import { UserManagementPanel } from "./components/UserManagementPanel";
import { DocumentList } from "./components/DocumentList";
import { SourceStatusBanner } from "./components/SourceStatusBanner";
import { UploadPanel } from "./components/UploadPanel";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentAnalysisPage } from "./pages/DocumentAnalysisPage";
import { ProjectWorkItemsPage } from "./pages/ProjectWorkItemsPage";
import { ChangePasswordPage, LoginPage } from "./pages/AuthPage";

type Mode = "documents" | "projects" | "dashboard" | "users" | "audit";

export default function App() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api.getMe().then(
      (current) => { if (mounted) setUser(current); },
      (err: unknown) => {
        if (!mounted) return;
        if (!(err instanceof ApiError && err.status === 401)) {
          setSessionError(err instanceof ApiError ? err.message : "無法連線到平台");
        }
      },
    ).finally(() => { if (mounted) setCheckingSession(false); });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    const expireSession = () => setUser(null);
    window.addEventListener("eq:unauthorized", expireSession);
    return () => window.removeEventListener("eq:unauthorized", expireSession);
  }, []);

  if (checkingSession) return <main className="auth-shell"><p>確認登入狀態中…</p></main>;
  if (sessionError && !user) {
    return <main className="auth-shell"><section className="card auth-card"><h1>無法連線</h1><p className="error">{sessionError}</p><button onClick={() => window.location.reload()}>重新載入</button></section></main>;
  }
  if (!user) return <LoginPage onLogin={setUser} />;
  if (user.must_change_password) {
    return <ChangePasswordPage user={user} onChanged={() => setUser(null)} />;
  }
  return <Workspace user={user} onLogout={async () => {
    try { await api.logout(); } catch { /* clear local state when the server is unreachable */ }
    setUser(null);
  }} />;
}

function Workspace({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const [mode, setMode] = useState<Mode>("documents");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourcesStatus, setSourcesStatus] = useState<SourcesStatus | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments((await api.listDocuments()).items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入文件清單");
    }
  }, []);

  useEffect(() => { void loadDocuments(); }, [loadDocuments]);
  useEffect(() => {
    api.getSourcesStatus().then(setSourcesStatus, () => setSourcesStatus(null));
  }, []);

  const selected = documents.find((doc) => doc.document_id === selectedId) ?? null;
  const isAdmin = user.role === "tenant_admin";
  const tabs: [Mode, string][] = [["documents", "文件分析"], ["projects", "專案工項"], ["dashboard", "總覽"]];
  if (isAdmin) tabs.push(["users", "使用者管理"], ["audit", "稽核紀錄"]);

  const openDocument = (documentId: string) => {
    // 總覽列出的文件可能是別的成員上傳的，本頁清單還沒有它
    void loadDocuments();
    setSelectedId(documentId);
    setMode("documents");
  };

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>工程法規符合性檢查平台</h1>
          <p className="hint">{user.tenant_name} · {user.username}</p>
        </div>
        <button type="button" className="secondary" onClick={() => void onLogout()}>登出</button>
      </header>

      <nav className="tabs">
        {tabs.map(([value, label]) => (
          <button key={value} type="button" className={mode === value ? "tab selected" : "tab"} onClick={() => setMode(value)}>
            {label}
          </button>
        ))}
      </nav>

      <SourceStatusBanner status={sourcesStatus} />
      {mode === "users" ? <UserManagementPanel />
        : mode === "audit" ? <AuditLogPanel />
        : mode === "dashboard" ? <DashboardPage canCheckChanges={isAdmin} onOpenDocument={openDocument} />
        : mode === "projects" ? <ProjectWorkItemsPage /> : (
        <div className="layout">
          <div className="sidebar">
            <UploadPanel onUploaded={(doc) => { void loadDocuments(); setSelectedId(doc.document_id); }} />
            <DocumentList documents={documents} selectedId={selectedId} onSelect={setSelectedId} />
            {error && <p className="error">{error}</p>}
          </div>
          <main>
            {selected ? (
              <DocumentAnalysisPage documentId={selected.document_id} filename={selected.filename} onDocumentChanged={() => void loadDocuments()} />
            ) : (
              <section className="card">
                <h2>請先選擇或上傳一份文件</h2>
                <p className="hint">選好文件後按「開始分析」，系統會在背景執行解析、抽取、正規化與比對，完成後即可檢視清單、逐筆覆核並匯出報告。</p>
              </section>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
