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

export function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-TW", { hour12: false });
}
