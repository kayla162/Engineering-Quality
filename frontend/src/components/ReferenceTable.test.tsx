import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReferenceSummary } from "../api/types";
import { SummaryBar } from "./ReferenceTable";

const NOTHING: ReferenceSummary = {
  confirmed_active: 0,
  possible_amended: 0,
  possible_repealed: 0,
  possible_match: 0,
  not_found: 0,
  unknown: 0,
};

describe("SummaryBar", () => {
  it("沒有查詢失敗時不多嘴", () => {
    render(<SummaryBar summary={{ ...NOTHING, confirmed_active: 3 }} />);

    expect(screen.queryByText(/法規來源/)).not.toBeInTheDocument();
  });

  it("有查詢失敗時說明常見原因與下一步", () => {
    // 來源就緒後重跑分析之前，舊報告仍會滿是「查詢失敗」，
    // 這時全域橫幅已經消失，只剩這裡能解釋畫面上看到的東西。
    render(<SummaryBar summary={{ ...NOTHING, unknown: 12 }} />);

    expect(screen.getByText(/12 筆/)).toBeInTheDocument();
    expect(screen.getByText(/法規來源/)).toBeInTheDocument();
    expect(screen.getByText(/重新分析/)).toBeInTheDocument();
  });
});
