// 唯一一個跟後端說話的地方。要改 API 路徑或錯誤處理都在這裡。

import type {
  DocumentList,
  DocumentRole,
  DocumentSummary,
  Job,
  Project,
  ProjectDocumentLink,
  ProjectList,
  ReferenceDetail,
  ReferenceFilters,
  ReferenceList,
  ReviewStatus,
  SourcesStatus,
  WorkItemList,
} from "./types";

const BASE = "/api";

/** 後端統一錯誤格式 {"error": {code, message, details}} */
export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    let code = "UNKNOWN";
    let message = `請求失敗（HTTP ${response.status}）`;
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      // 回應不是 JSON，沿用預設訊息
    }
    throw new ApiError(code, message, response.status);
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number | undefined | "">): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  /** 法規來源現在查不查得動。前端據此在來源未就緒時提示，而不是讓使用者面對滿頁「查詢失敗」 */
  getSourcesStatus: () => request<SourcesStatus>("/sources"),

  listDocuments: (page = 1, pageSize = 20) =>
    request<DocumentList>(`/documents${query({ page, page_size: pageSize })}`),

  getDocument: (documentId: string) =>
    request<DocumentSummary>(`/documents/${documentId}`),

  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentSummary>("/documents/upload", { method: "POST", body: form });
  },

  startAnalysis: (documentId: string) =>
    request<{ job_id: string; status: string }>(`/documents/${documentId}/analyze`, {
      method: "POST",
    }),

  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),

  listReferences: (documentId: string, filters: ReferenceFilters, page = 1, pageSize = 100) =>
    request<ReferenceList>(
      `/documents/${documentId}/references${query({
        status: filters.status,
        review_status: filters.review_status,
        min_confidence: filters.min_confidence,
        page,
        page_size: pageSize,
      })}`,
    ),

  getReference: (referenceId: string) =>
    request<ReferenceDetail>(`/regulation-references/${referenceId}`),

  reviewReference: (
    referenceId: string,
    payload: { review_status: ReviewStatus; reviewed_by: string; review_note?: string },
  ) =>
    request<ReferenceDetail>(`/regulation-references/${referenceId}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listProjects: () => request<ProjectList>("/projects"),

  createProject: (name: string) =>
    request<Project>("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  /** 角色決定跑什麼管線：標單走工項抽取，契約與規範走法規抽取 */
  attachDocument: (projectId: string, documentId: string, role: DocumentRole) =>
    request<ProjectDocumentLink>(`/projects/${projectId}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, role }),
    }),

  /** 從專案的標單重建工項清單。重跑會取代舊的，不是累加。 */
  buildWorkItems: (projectId: string) =>
    request<WorkItemList>(`/projects/${projectId}/work-items`, { method: "POST" }),

  listWorkItems: (projectId: string) =>
    request<WorkItemList>(`/projects/${projectId}/work-items`),

  /** 匯出是檔案下載，直接開新分頁交給瀏覽器處理 */
  exportReportUrl: (documentId: string, format: "xlsx" | "csv" | "pdf") =>
    `${BASE}/reports/${documentId}/export?format=${format}`,
};
