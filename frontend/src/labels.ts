// 所有給使用者看的中文標籤集中在這裡，要改詞彙只需要改這一個檔案。

import type { RegulationStatus, ReviewStatus, SourceAvailability } from "./api/types";

export const STATUS_LABELS: Record<RegulationStatus, string> = {
  ACTIVE: "現行有效",
  AMENDED: "已修正",
  REPEALED: "已廢止",
  NOT_FOUND: "查無此法規",
  POSSIBLE_MATCH: "疑似對應",
  UNKNOWN: "查詢失敗",
};

/** 法規來源未就緒時的警告文案。先說後果，再說怎麼辦——只說「有問題」沒有用。 */
export const SOURCE_WARNINGS: Record<
  Exclude<SourceAvailability, "ok">,
  { headline: string; consequence: string }
> = {
  degraded: {
    headline: "部分法規來源尚未就緒",
    consequence:
      "分析仍可進行，但涵蓋範圍會比預期小：屬於下列來源的法規會查不到，可能被標成「查無此法規」。",
  },
  unavailable: {
    headline: "法規來源尚未就緒",
    consequence:
      "現在分析的話，每一筆引用都會是「查詢失敗」。請先讓下列來源就緒，再重新分析。",
  },
};

/** 需要人工介入的狀態，畫面上會標色 */
export const NEEDS_ATTENTION: RegulationStatus[] = [
  "AMENDED",
  "REPEALED",
  "NOT_FOUND",
  "POSSIBLE_MATCH",
  "UNKNOWN",
];

export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  UNREVIEWED: "未覆核",
  CONFIRMED: "已確認",
  REJECTED: "已否決",
};

export const CHECK_RESULT_LABELS: Record<string, string> = {
  OK: "OK",
  SPEC_NOT_INCLUDED: "本案規範未收錄",
  NEEDS_CONFIRMATION: "請確認依據",
};

/**
 * 查證狀態。null 要顯示成「未查證」，**不是**「查無此法規」——
 * 那個說法會讓人以為規範書引用了不存在的東西。
 * 這張表刻意不放 NOT_FOUND：檢核表的查證只採完全同名，找不到就是沒查證，不是查無。
 */
export const VERIFICATION_LABELS: Record<string, string> = {
  ACTIVE: "現行有效",
  AMENDED: "已修正",
  REPEALED: "已廢止",
};

export const UNVERIFIED_LABEL = "未查證";

export const TYPE_LABELS: Record<string, string> = {
  law: "法律",
  regulation: "法規命令",
  standard: "標準",
  engineering_spec: "工程規範",
  contract_spec: "契約規範",
  announcement: "公告/要點",
  other: "其他",
};

export const STEP_LABELS: Record<string, string> = {
  PARSING: "文件解析中",
  EXTRACTING: "法規抽取中",
  NORMALIZING: "名稱正規化中",
  MATCHING: "比對中",
  QUERYING: "查詢法規來源中",
  REPORTING: "產生報告中",
};

export const METHOD_LABELS: Record<string, string> = {
  regex: "規則比對",
  dictionary: "別名字典",
  ner: "命名實體辨識",
  llm_fallback: "AI 輔助抽取",
};

export const AI_PURPOSE_LABELS: Record<string, string> = {
  extraction: "抽取",
  similarity_judgement: "相似度判斷",
  report_summary: "報告摘要",
};

/** audit_log.action 的顯示文字（後端定義在 app/core/enums.py 的 AuditAction） */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  login: "登入",
  login_failed: "登入失敗",
  logout: "登出",
  password_changed: "變更密碼",
  user_created: "新增使用者",
  user_deactivated: "停用使用者",
  user_reactivated: "重新啟用使用者",
  document_uploaded: "上傳文件",
  analysis_started: "開始分析",
  reference_reviewed: "人工覆核",
  report_exported: "匯出報告",
  project_created: "建立專案",
  project_document_attached: "專案掛上文件",
  work_items_built: "建立工項清單",
  checklist_built: "建立檢核表",
  regulation_verified: "重新查證法規",
  regulation_changes_checked: "檢查法規異動",
  regulation_change_acknowledged: "確認法規異動",
};

/** 法規異動的欄位名稱 */
export const CHANGE_FIELD_LABELS: Record<string, string> = {
  status: "狀態",
  effective_date: "生效日",
  last_amended_date: "最後修正日",
  presence: "來源資料",
};

/** 資料來源的顯示文字。mock 一定要讓人看出是假資料 */
export const SOURCE_LABELS: Record<string, string> = {
  taiwan_law: "全國法規資料庫",
  pcces: "施工綱要規範",
  mock: "假資料（僅供 Demo）",
  manual: "人工建立",
};

export function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

/** 結尾有 Z 或 +08:00 這類時區標記 */
const HAS_TIMEZONE = /(Z|[+-]\d{2}:?\d{2})$/;

export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  // 後端一律存 UTC。SQLite 不保存時區，回來的字串沒有時區標記，
  // 直接 new Date() 會被當成本地時間，台灣會差 8 小時。
  const iso = HAS_TIMEZONE.test(value) ? value : `${value}Z`;
  return new Date(iso).toLocaleString("zh-TW", { hour12: false });
}
