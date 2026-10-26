import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuditLogList } from "../api/types";
import { stubApi } from "../test/stubApi";
import { AuditLogPanel } from "./AuditLogPanel";

const LOGS: AuditLogList = {
  total: 2,
  page: 1,
  page_size: 50,
  items: [
    {
      audit_id: "a1",
      created_at: "2026-10-24T02:00:00Z",
      username: "admin",
      action: "reference_reviewed",
      resource_type: "reference",
      resource_id: "r1",
      detail: { raw_text: "採購法", review_status: "CONFIRMED", review_note: "已查證" },
      ip_address: "127.0.0.1",
    },
    {
      audit_id: "a2",
      created_at: "2026-10-24T01:00:00Z",
      username: "member",
      action: "login_failed",
      resource_type: null,
      resource_id: null,
      detail: { reason: "invalid_credentials" },
      ip_address: "10.0.0.5",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuditLogPanel", () => {
  it("用中文顯示操作與內容", async () => {
    stubApi({ "/api/audit-logs": LOGS });

    render(<AuditLogPanel />);

    expect(await screen.findByText("人工覆核")).toBeInTheDocument();
    expect(screen.getByText("採購法 · CONFIRMED · 已查證")).toBeInTheDocument();
  });

  it("登入失敗標色", async () => {
    stubApi({ "/api/audit-logs": LOGS });

    render(<AuditLogPanel />);

    const row = (await screen.findByText("登入失敗", { selector: "td" })).closest("tr");
    expect(row).toHaveClass("attention");
  });

  it("依操作篩選會帶參數查詢", async () => {
    const calls = stubApi({ "/api/audit-logs": LOGS });

    render(<AuditLogPanel />);
    await screen.findByText("人工覆核", { selector: "td" });
    fireEvent.change(screen.getByLabelText(/操作/), { target: { value: "login_failed" } });

    await vi.waitFor(() =>
      expect(calls.some((call) => call.includes("action=login_failed"))).toBe(true),
    );
  });
});
