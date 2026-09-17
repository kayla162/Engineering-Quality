import type { DocumentSummary } from "../api/types";
import { formatDateTime } from "../labels";

export function DocumentList({
  documents,
  selectedId,
  onSelect,
}: {
  documents: DocumentSummary[];
  selectedId: string | null;
  onSelect: (documentId: string) => void;
}) {
  if (documents.length === 0) {
    return (
      <section className="card">
        <h2>文件清單</h2>
        <p className="hint">還沒有任何文件，請先上傳。</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>文件清單</h2>
      <table>
        <thead>
          <tr>
            <th>檔名</th>
            <th>格式</th>
            <th>狀態</th>
            <th>上傳時間</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.document_id}
              className={doc.document_id === selectedId ? "selected clickable" : "clickable"}
              onClick={() => onSelect(doc.document_id)}
            >
              <td>{doc.filename}</td>
              <td>{doc.file_type}</td>
              <td>{doc.status}</td>
              <td>{formatDateTime(doc.uploaded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
