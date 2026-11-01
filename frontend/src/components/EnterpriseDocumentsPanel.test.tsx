import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EnterpriseDocumentList } from "../api/types";
import { stubApi } from "../test/stubApi";
import { EnterpriseDocumentsPanel } from "./EnterpriseDocumentsPanel";

const EMPTY: EnterpriseDocumentList = { total: 0, imported_at: null, imported_by: null, items: [] };

const LIST: EnterpriseDocumentList = {
  total: 2,
  imported_at: "2026-11-01T02:00:00Z",
  imported_by: "admin",
  items: [
    {
      document_id: "e1",
      doc_number: "QP-07-01",
      name: "模板組立作業標準",
      doc_type: "作業標準（SOP）",
      revision: "第2版",
      effective_date: "2019-05-01",
      last_revised_date: null,
      status: "REPEALED",
      status_label: "作廢",
      replaced_by: "QP-07-06",
      owner: "工務部",
      aliases: [],
      note: null,
    },
    {
      document_id: "e2",
      doc_number: "QP-07-03",
      name: "混凝土澆置作業標準",
      doc_type: "作業標準（SOP）",
      revision: "第5版",
      effective_date: "2025-03-01",
      last_revised_date: "2025-02-20",
      status: "ACTIVE",
      status_label: "現行",
      replaced_by: null,
      owner: "工務部",
      aliases: ["澆置SOP"],
      note: null,
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function upload() {
  const file = new File(["PK"], "清單.xlsx");
  fireEvent.change(screen.getByLabelText("匯入企業內部文件清單"), { target: { files: [file] } });
}

describe("EnterpriseDocumentsPanel", () => {
  it("列出文件，作廢的標出取代文件", async () => {
    stubApi({ "/api/enterprise-documents": LIST });

    render(<EnterpriseDocumentsPanel canImport onImported={vi.fn()} />);

    expect(await screen.findByText("模板組立作業標準")).toBeInTheDocument();
    expect(screen.getByText("（已由 QP-07-06 取代）")).toBeInTheDocument();
    expect(screen.getByText("已廢止")).toBeInTheDocument();
  });

  it("沒有清單時，管理員看到要下載範本", async () => {
    stubApi({ "/api/enterprise-documents": EMPTY });

    render(<EnterpriseDocumentsPanel canImport onImported={vi.fn()} />);

    expect(await screen.findByText(/請下載範本/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下載範本" })).toHaveAttribute(
      "href",
      "/api/enterprise-documents/template",
    );
  });

  it("一般成員不能匯入", async () => {
    stubApi({ "/api/enterprise-documents": EMPTY });

    render(<EnterpriseDocumentsPanel canImport={false} onImported={vi.fn()} />);

    expect(await screen.findByText(/請租戶管理員匯入/)).toBeInTheDocument();
    expect(screen.queryByLabelText("匯入企業內部文件清單")).not.toBeInTheDocument();
  });

  it("匯入成功後顯示新清單並通知上層", async () => {
    stubApi({ "/api/enterprise-documents/import": LIST, "/api/enterprise-documents": EMPTY });
    const onImported = vi.fn();

    render(<EnterpriseDocumentsPanel canImport onImported={onImported} />);
    await screen.findByText(/請下載範本/);
    upload();

    expect(await screen.findByRole("status")).toHaveTextContent("已匯入 2 份文件");
    expect(screen.getByText("混凝土澆置作業標準")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalled();
  });

  it("匯入失敗時逐列列出錯誤", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/import")) {
          return new Response(
            JSON.stringify({
              error: {
                code: "ENTERPRISE_IMPORT_INVALID",
                message: "清單有 1 處錯誤，整份未匯入",
                details: [{ row: 6, message: "狀態「停用」無效，只能是：現行、已修訂、作廢" }],
              },
            }),
            { status: 400, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify(EMPTY), { headers: { "Content-Type": "application/json" } });
      }),
    );

    render(<EnterpriseDocumentsPanel canImport onImported={vi.fn()} />);
    await screen.findByText(/請下載範本/);
    upload();

    expect(await screen.findByText("清單有 1 處錯誤，整份未匯入")).toBeInTheDocument();
    expect(screen.getByText("第 6 列：狀態「停用」無效，只能是：現行、已修訂、作廢")).toBeInTheDocument();
  });
});
