// 唯一一個跟後端說話的地方。要改 API 路徑或錯誤處理都在這裡。

import type {
  AuditLogList,
  ChangeCheckResult,
  Checklist,
  Dashboard,
  DocumentList,
  DocumentRole,
  DocumentSummary,
  Job,
  ManagedUser,
  Project,
  ProjectDocumentLink,
  ProjectList,
  ReferenceDetail,
  ReferenceFilters,
  ReferenceList,
  RegulationChange,
  ReviewStatus,
  SourcesStatus,
  SessionUser,
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
  const response = await fetch(`${BASE}${path}`, { credentials: "same-origin", ...init });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("eq:unauthorized"));
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
  if (response.status === 204) return undefined as T;
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
  login: (username: string, password: string) =>
    request<SessionUser>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),

  getMe: () => request<SessionUser>("/auth/me"),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  changePassword: (old_password: string | undefined, new_password: string) =>
    request<void>("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password, new_password }),
    }),

  listUsers: () => request<{ total: number; items: ManagedUser[] }>("/users"),

  createUser: (username: string, initial_password: string, role: ManagedUser["role"]) =>
    request<ManagedUser>("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, initial_password, role }),
    }),

  deactivateUser: (userId: string) =>
    request<ManagedUser>(`/users/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: false }),
    }),

  reactivateUser: (userId: string, initial_password: string) =>
    request<ManagedUser>(`/users/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: true, initial_password }),
    }),

  listAuditLogs: (filters: { action?: string; username?: string }, page = 1, pageSize = 50) =>
    request<AuditLogList>(
      `/audit-logs${query({ action: filters.action, username: filters.username, page, page_size: pageSize })}`,
    ),

  getDashboard: () => request<Dashboard>("/dashboard"),

  listRegulationChanges: (includeAcknowledged = false) =>
    request<{ total: number; items: RegulationChange[] }>(
      `/regulation-changes${query({ include_acknowledged: includeAcknowledged ? "true" : undefined })}`,
    ),

  checkRegulationChanges: () =>
    request<ChangeCheckResult>("/regulation-changes/check", { method: "POST" }),

  acknowledgeRegulationChange: (changeId: string) =>
    request<RegulationChange>(`/regulation-changes/${changeId}/acknowledge`, { method: "POST" }),

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
    payload: { review_status: ReviewStatus; review_note?: string },
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

  /** 重建依據（重讀規範書、重抽取、重查證）並回傳檢核表。重跑取代，不累加。 */
  buildChecklist: (projectId: string) =>
    request<Checklist>(`/projects/${projectId}/checklist`, { method: "POST" }),

  /** 只讀已經建好的依據，不重建。要更新依據請用 buildChecklist。 */
  getChecklist: (projectId: string) => request<Checklist>(`/projects/${projectId}/checklist`),

  /** 匯出是檔案下載，直接開新分頁交給瀏覽器處理 */
  exportReportUrl: (documentId: string, format: "xlsx" | "csv" | "pdf") =>
    `${BASE}/reports/${documentId}/export?format=${format}`,
};
