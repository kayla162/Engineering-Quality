import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReferenceDetail } from "../api/types";
import { stubApi } from "../test/stubApi";
import { ReferenceDetailPanel } from "./ReferenceDetailPanel";

const DETAIL: ReferenceDetail = {
  reference_id: "ref1",
  raw_text: "新北市樹木保護自治條例",
  normalized_name: "新北市樹木保護自治條例",
  regulation_type: "law",
  article: null,
  standard_number: null,
  source_document: "1.契約書.pdf",
  page: 12,
  section_text: "移植樹木應依新北市樹木保護自治條例辦理。",
  section_is_ocr: false,
  extraction_method: "regex",
  extraction_confidence: 0.8,
  matched_regulation: {
    regulation_id: "r1",
    name: "新北市樹木保護自治條例",
    type: "law",
    status: "ACTIVE",
    authority: "新北市政府",
    effective_date: null,
    last_amended_date: null,
    official_url: null,
    source: "admin_rules",
    source_note: "地方法規（示範目錄）：名稱取自契約書；狀態「現行」為假資料，日期未查證",
  },
  match_confidence: 1,
  match_reasons: [],
  status: "ACTIVE",
  is_tentative: false,
  review_status: "UNREVIEWED",
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  query_history: [],
  ai_invocations: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReferenceDetailPanel", () => {
  it("示範目錄的出處要讓人看到哪些是假資料", async () => {
    stubApi({ "/api/regulation-references/ref1": DETAIL });

    render(<ReferenceDetailPanel referenceId="ref1" onReviewed={vi.fn()} />);

    expect(await screen.findByText(/狀態「現行」為假資料，日期未查證/)).toBeInTheDocument();
  });

  it("其他來源沒有出處說明時不顯示", async () => {
    const official = {
      ...DETAIL,
      matched_regulation: { ...DETAIL.matched_regulation!, source: "taiwan_law", source_note: null },
    };
    stubApi({ "/api/regulation-references/ref1": official });

    render(<ReferenceDetailPanel referenceId="ref1" onReviewed={vi.fn()} />);

    expect(await screen.findByText("taiwan_law")).toBeInTheDocument();
    expect(screen.queryByText(/示範目錄/)).not.toBeInTheDocument();
  });
});
