import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stubApi } from "../test/stubApi";
import { ProjectWorkItemsPage } from "./ProjectWorkItemsPage";

const PROJECT = {
  project_id: "p1",
  name: "秀山分隊興建工程",
  created_at: "2026-09-17T08:00:00Z",
};

const ONE_PROJECT = { total: 1, items: [PROJECT] };
const NO_PROJECTS = { total: 0, items: [] };
const NO_DOCUMENTS = { total: 0, page: 1, page_size: 20, items: [] };

const WORK_ITEMS = {
  total: 1028,
  with_spec_chapter: 438,
  items: [
    {
      work_item_id: "w1",
      item_no: "壹.一.1.1.1",
      name: "施工測量，基地測量及鑑界費",
      unit: "式",
      quantity: "1",
      cost_code: "0172500004",
      spec_chapter: { code: "01725", name: "公共工程施工綱要規範第01725章 施工測量" },
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProjectWorkItemsPage", () => {
  it("還沒有專案時引導使用者先建立一個", async () => {
    stubApi({ "/api/projects": NO_PROJECTS, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);

    expect(await screen.findByText(/先建立一個專案/)).toBeInTheDocument();
  });

  it("選定專案後載入它的工項並顯示統計", async () => {
    stubApi({
      "/api/projects/p1/work-items": WORK_ITEMS,
      "/api/projects": ONE_PROJECT,
      "/api/documents": NO_DOCUMENTS,
    });

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByText("秀山分隊興建工程"));

    expect(await screen.findByText("1028")).toBeInTheDocument();
    expect(screen.getByText("438")).toBeInTheDocument();
    expect(screen.getByText("壹.一.1.1.1")).toBeInTheDocument();
  });

  it("建立專案時打的是 POST /api/projects", async () => {
    const calls = stubApi({ "/api/projects": ONE_PROJECT, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);
    fireEvent.change(await screen.findByLabelText(/專案名稱/), {
      target: { value: "新工程" },
    });
    fireEvent.click(screen.getByRole("button", { name: /建立專案/ }));

    expect(await screen.findByText("秀山分隊興建工程")).toBeInTheDocument();
    expect(calls).toContain("POST /api/projects");
  });

  it("名稱是空的時候不送出", async () => {
    const calls = stubApi({ "/api/projects": NO_PROJECTS, "/api/documents": NO_DOCUMENTS });

    render(<ProjectWorkItemsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /建立專案/ }));

    expect(calls.filter((call) => call.startsWith("POST"))).toHaveLength(0);
  });
});
