// 後端 API 的資料型別。欄位對應 backend/app/schemas/。

export type RegulationStatus =
  | "ACTIVE"
  | "AMENDED"
  | "REPEALED"
  | "NOT_FOUND"
  | "POSSIBLE_MATCH"
  | "UNKNOWN";

export type ReviewStatus = "UNREVIEWED" | "CONFIRMED" | "REJECTED";

export interface SessionUser {
  user_id: string;
  username: string;
  role: "tenant_admin" | "member";
  tenant_id: string;
  tenant_name: string;
  must_change_password: boolean;
}

export interface ManagedUser {
  user_id: string;
  username: string;
  role: "tenant_admin" | "member";
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
}

/** 已啟用的法規來源整體上查不查得動（GET /api/sources） */
export type SourceAvailability = "ok" | "degraded" | "unavailable";

export interface SourceReadiness {
  source: string;
  /** 未就緒的原因，含檔案路徑。就緒時為 null */
  detail: string | null;
  /** 讓它就緒要跑的命令。沒有可執行的動作時為 null */
  remedy: string | null;
  ready: boolean;
}

export interface SourcesStatus {
  status: SourceAvailability;
  sources: SourceReadiness[];
}

export interface JobBrief {
  job_id: string;
  status: string;
  progress: number;
  finished_at: string | null;
}

export interface DocumentSummary {
  document_id: string;
  filename: string;
  file_type: string;
  status: string;
  uploaded_at: string;
  latest_job: JobBrief | null;
}

export interface DocumentList {
  total: number;
  page: number;
  page_size: number;
  items: DocumentSummary[];
}

export interface Job {
  job_id: string;
  document_id: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  current_step: string | null;
  progress: number;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
}

export interface ReferenceSummary {
  confirmed_active: number;
  possible_amended: number;
  possible_repealed: number;
  possible_match: number;
  not_found: number;
  unknown: number;
}

export interface ReferenceItem {
  reference_id: string;
  raw_text: string;
  normalized_name: string | null;
  regulation_type: string;
  article: string | null;
  page: number | null;
  status: RegulationStatus;
  match_confidence: number | null;
  review_status: ReviewStatus;
  regulation_id: string | null;
  is_tentative: boolean;
}

export interface ReferenceList {
  total: number;
  page: number;
  page_size: number;
  summary: ReferenceSummary;
  items: ReferenceItem[];
}

export interface MatchedRegulation {
  regulation_id: string;
  name: string;
  type: string;
  status: RegulationStatus;
  authority: string | null;
  effective_date: string | null;
  last_amended_date: string | null;
  official_url: string | null;
  source: string;
}

export interface QueryHistoryItem {
  source: string;
  query: string;
  http_status: string | null;
  latency_ms: number | null;
  queried_at: string;
}

export interface AIInvocationItem {
  purpose: string;
  model: string;
  prompt_version: string;
  confidence: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface ReferenceDetail {
  reference_id: string;
  raw_text: string;
  normalized_name: string | null;
  regulation_type: string;
  article: string | null;
  standard_number: string | null;
  source_document: string;
  page: number | null;
  section_text: string | null;
  extraction_method: string;
  extraction_confidence: number;
  matched_regulation: MatchedRegulation | null;
  match_confidence: number | null;
  match_reasons: string[];
  status: RegulationStatus;
  is_tentative: boolean;
  review_status: ReviewStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  query_history: QueryHistoryItem[];
  ai_invocations: AIInvocationItem[];
}

export interface ReferenceFilters {
  status?: RegulationStatus | "";
  review_status?: ReviewStatus | "";
  min_confidence?: number | "";
}

// --- 專案與工項（backend/app/schemas/project.py）---

/** 文件在專案裡扮演的角色。決定跑哪條管線：標單走工項抽取，其餘走法規抽取。 */
export type DocumentRole = "boq" | "contract" | "drawing" | "specification" | "other";

export interface Project {
  project_id: string;
  name: string;
  created_at: string;
}

export interface ProjectList {
  total: number;
  items: Project[];
}

/** 由計價代碼前 5 碼查出來的施工綱要規範章節。對不到就是 null，不硬湊。 */
export interface SpecChapter {
  code: string;
  name: string;
}

export interface WorkItem {
  work_item_id: string;
  item_no: string;
  name: string;
  unit: string;
  quantity: string;
  cost_code: string | null;
  spec_chapter: SpecChapter | null;
}

export interface WorkItemList {
  total: number;
  /** 有對到綱要規範章節的筆數。實測真實標單 438/1028 */
  with_spec_chapter: number;
  items: WorkItem[];
}

export interface ProjectDocumentLink {
  document_id: string;
  role: string;
  added_at: string;
}

// --- 檢核表（backend/app/schemas/checklist.py）---

export type CheckResult = "OK" | "SPEC_NOT_INCLUDED" | "NEEDS_CONFIRMATION";

export interface Basis {
  basis_type: string;
  reference: string;
  detail: string | null;
  /** 法規查證結果。null 代表**未查證**，不是「查無此法規」。 */
  verification_status: string | null;
}

export interface ChecklistItem {
  work_item_id: string;
  item_no: string;
  name: string;
  result: CheckResult;
  /** 計價代碼前 5 碼。`chapter` 是 null 時，靠這個才說得出缺的是哪一章。 */
  chapter_code: string | null;
  chapter: { code: string; title: string; version: string } | null;
  bases: Basis[];
}

export interface Checklist {
  total: number;
  summary: { ok: number; spec_not_included: number; needs_confirmation: number };
  contract_note: string;
  spec_warning: string | null;
  items: ChecklistItem[];
}
