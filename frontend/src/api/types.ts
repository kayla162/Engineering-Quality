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
  /** DEGRADED：有一部分內容讀不到或是 OCR 辨識的，note 說明是哪些頁 */
  parse_quality: "OK" | "DEGRADED";
  parse_quality_note: string | null;
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
  /** 示範目錄寫明的資料出處（哪些欄位是假資料） */
  source_note: string | null;
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
  /** 原始段落由 OCR 辨識而來，可能有錯字 */
  section_is_ocr: boolean;
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

export type CheckResult =
  | "OK"
  | "SPEC_NOT_INCLUDED"
  | "NEEDS_CONFIRMATION"
  | "BOQ_NOT_IN_DRAWINGS"
  | "METHOD_UNDECIDED";

export interface DrawingSheet {
  sheet_no: string;
  title: string;
  page: number;
  /** 由 OCR 從掃描的標題欄讀出，可能有錯字；圖號讀不到時是「第N頁」 */
  is_ocr?: boolean;
}

/** 契約書提到這個工項的一處。條號是 Word 自動編號、PDF 讀不到，所以只有頁碼與前面最近的標題。 */
export interface ContractRef {
  page: number | null;
  heading: string | null;
  excerpt: string;
  /** 用哪個詞找到的（工項或所屬分項的主體） */
  keyword: string;
}

/** 工法欄：施工規範列出多種工法時才有。selected 是 null 代表契約文件沒指定。 */
export interface WorkItemMethod {
  options: string[];
  selected: string | null;
  evidence: string | null;
}

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
  /** 所有成立的問題，依優先序；result 是第一個 */
  issues: CheckResult[];
  /** 圖名和工項相關的契約圖 */
  drawings: DrawingSheet[];
  method: WorkItemMethod | null;
  /** 契約書提到這個工項的地方（舊版後端沒有這個欄位） */
  contract_refs?: ContractRef[];
}

export interface Checklist {
  total: number;
  summary: {
    ok: number;
    spec_not_included: number;
    needs_confirmation: number;
    boq_not_in_drawings: number;
    method_undecided: number;
  };
  contract_note: string;
  spec_warning: string | null;
  /** 有讀得到圖號的契約圖才判斷「標單有，契約圖沒有」 */
  has_drawings: boolean;
  /** 掛了契約圖卻一張都讀不到（多半是掃描檔）時的說明 */
  drawing_warning: string | null;
  /** 契約圖有、標單沒有（專案層級） */
  drawings_without_items: DrawingSheet[];
  items: ChecklistItem[];
}

export interface AuditLogItem {
  audit_id: string;
  created_at: string;
  username: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown> | null;
  ip_address: string | null;
}

export interface AuditLogList {
  total: number;
  page: number;
  page_size: number;
  items: AuditLogItem[];
}

export interface Dashboard {
  documents: {
    total: number;
    by_status: Record<string, number>;
    degraded: number;
    failed: number;
  };
  references: {
    total: number;
    by_status: Partial<Record<RegulationStatus, number>>;
    by_review: Partial<Record<ReviewStatus, number>>;
    /** 狀態需要人工介入、且還沒覆核過 */
    needs_action: number;
    by_source: Record<string, number>;
  };
  projects: number;
  open_regulation_changes: number;
  top_regulations: {
    regulation_id: string;
    name: string;
    status: RegulationStatus;
    source: string;
    references: number;
    documents: number;
  }[];
  documents_needing_action: {
    document_id: string;
    filename: string;
    parse_quality: "OK" | "DEGRADED";
    references: number;
    unreviewed: number;
    needs_action: number;
  }[];
}

export interface RegulationChange {
  change_id: string;
  regulation_id: string;
  regulation_name: string;
  current_status: RegulationStatus;
  source: string;
  /** {"status": {"old": "ACTIVE", "new": "REPEALED"}}；來源查不到時是 presence */
  changes: Record<string, { old: string | null; new: string | null }>;
  detected_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  affected_documents: { document_id: string; filename: string; references: number }[];
}

export interface ChangeCheckResult {
  checked: number;
  changed: number;
  skipped: { regulation_id: string; name: string; reason: string }[];
  new_changes: RegulationChange[];
}

export interface EnterpriseDocument {
  document_id: string;
  doc_number: string;
  name: string;
  doc_type: string;
  revision: string;
  effective_date: string;
  last_revised_date: string | null;
  status: RegulationStatus;
  /** 範本上的原文：現行 / 已修訂 / 作廢 */
  status_label: string;
  replaced_by: string | null;
  owner: string | null;
  aliases: string[];
  note: string | null;
}

export interface EnterpriseDocumentList {
  total: number;
  imported_at: string | null;
  imported_by: string | null;
  items: EnterpriseDocument[];
}

export interface SearchResult {
  query: string;
  /** 檢索方式的說明（示範版是字詞相似度，不是語意） */
  method_note: string;
  sections: {
    document_id: string;
    filename: string;
    page: number | null;
    snippet: string;
    score: number;
    matched: string[];
  }[];
  regulations: {
    regulation_id: string;
    name: string;
    status: string;
    source: string;
    score: number;
  }[];
}
