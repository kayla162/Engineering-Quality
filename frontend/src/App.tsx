import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "./api/client";
import type { DocumentSummary, SourcesStatus } from "./api/types";
import { DocumentList } from "./components/DocumentList";
import { SourceStatusBanner } from "./components/SourceStatusBanner";
import { UploadPanel } from "./components/UploadPanel";
import { DocumentAnalysisPage } from "./pages/DocumentAnalysisPage";

export default function App() {
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

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // 來源未就緒時每一筆引用都會是「查詢失敗」，所以在使用者按下分析之前就先問。
  // 問不到就當作沒事（null）：後端整個掛掉時，文件清單的錯誤訊息已經會說話了。
  useEffect(() => {
    api.getSourcesStatus().then(setSourcesStatus, () => setSourcesStatus(null));
  }, []);

  const selected = documents.find((doc) => doc.document_id === selectedId) ?? null;

  return (
    <div className="app">
      <header>
        <h1>工程法規符合性檢查平台</h1>
        <p className="hint">
          上傳工程文件，系統會抽出其中引用的法規與標準，查詢其狀態，並標示需要人工確認的項目。
        </p>
      </header>

      <SourceStatusBanner status={sourcesStatus} />

      <div className="layout">
        <div className="sidebar">
          <UploadPanel
            onUploaded={(doc) => {
              void loadDocuments();
              setSelectedId(doc.document_id);
            }}
          />
          <DocumentList
            documents={documents}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          {error && <p className="error">{error}</p>}
        </div>

        <main>
          {selected ? (
            <DocumentAnalysisPage
              documentId={selected.document_id}
              filename={selected.filename}
              onDocumentChanged={() => void loadDocuments()}
            />
          ) : (
            <section className="card">
              <h2>請先選擇或上傳一份文件</h2>
              <p className="hint">
                選好文件後按「開始分析」，系統會在背景執行解析、抽取、正規化與比對，
                完成後即可檢視清單、逐筆覆核並匯出報告。
              </p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
