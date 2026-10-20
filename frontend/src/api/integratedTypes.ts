import type { Basis, ChecklistItem } from "./types";

export interface IntegratedDrawing {
  id: string; sheet_id: string; document_id: string; filename: string | null; page: number;
  number: string | null; title: string | null; evidence: string; sheet_evidence: string;
  review_status: string; review_note: string; warning: string | null;
}
export interface IntegratedItem {
  key: string; work_item_id: string | null; item_no: string | null; name: string;
  source_status: string; basis_result: string | null; chapter_code: string | null;
  chapter: ChecklistItem["chapter"]; bases: Basis[]; drawings: IntegratedDrawing[];
  method: { status: string; candidates: { text: string; source: string; evidence: string; drawing_item_id?: string | null }[] };
}
export interface IntegratedChecklist {
  project_id: string; revision: number; total: number; summary: Record<string, number>;
  warnings: string[]; contract_note: string; items: IntegratedItem[];
}
export interface InspectionGroup {
  id: string; key: string; names: string[]; occurrence_count: number; page_count: number;
  items: { id: string; name: string; sheet_id: string; document_id: string; page: number;
    number: string | null; title: string | null; review_status: string; review_note: string; document_url: string }[];
}
export interface InspectionFinding {
  id: string; kind: string; priority: string; source_page: number | null; source_number: string | null;
  title: string; message: string; quote: string | null; document_id: string | null; document_url: string | null;
  targets: { book: string; page: number; number: string; title: string }[];
}
export interface DrawingInspection {
  project_id: string; available: boolean; revision: number; historical_revision: number | null; warnings: string[];
  summary: { current_candidates: number; current_name_groups: number; current_statuses: Record<string, number>;
    historical_name_groups: number; historical_similar_hints: number; index_title_differences: number;
    references: number; reference_counts: Record<string, number> };
  groups: InspectionGroup[];
  similar_hints: { left: string; right: string; left_name: string; right_name: string; reason: string;
    similarity: number; decision: string }[];
  findings: InspectionFinding[];
  images: { id: string; label: string; url: string }[];
  historical_summary: Record<string, unknown>;
}
