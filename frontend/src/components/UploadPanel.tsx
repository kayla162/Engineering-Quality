import { useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import type { DocumentSummary } from "../api/types";

export function UploadPanel({ onUploaded }: { onUploaded: (doc: DocumentSummary) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      onUploaded(await api.uploadDocument(file));
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上傳失敗");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>上傳工程文件</h2>
      <p className="hint">
        支援 .docx / .pdf / .txt / .xls / .xlsx，預設上限 300MB。
        掃描圖說請上傳後掛到專案的「契約圖」，再使用圖說索引的本機 OCR。
      </p>
      <input
        ref={inputRef}
        type="file"
        accept=".docx,.pdf,.txt,.xls,.xlsx"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
        }}
      />
      {busy && <p className="hint">上傳中…</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
