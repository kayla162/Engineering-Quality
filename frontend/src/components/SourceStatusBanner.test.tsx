import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SourceReadiness, SourcesStatus } from "../api/types";
import { SourceStatusBanner } from "./SourceStatusBanner";

const UNSYNCED: SourceReadiness = {
  source: "taiwan_law",
  ready: false,
  detail: "找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）",
  remedy: "python scripts/sync_taiwan_law.py",
};

const READY: SourceReadiness = { source: "mock", ready: true, detail: null, remedy: null };

const status = (value: SourcesStatus["status"], sources: SourceReadiness[]): SourcesStatus => ({
  status: value,
  sources,
});

describe("SourceStatusBanner", () => {
  it("來源都就緒時不佔畫面", () => {
    const { container } = render(<SourceStatusBanner status={status("ok", [READY])} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("狀態還沒載入時不佔畫面", () => {
    const { container } = render(<SourceStatusBanner status={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("全部未就緒時說出後果，而不是只說「有問題」", () => {
    render(<SourceStatusBanner status={status("unavailable", [UNSYNCED])} />);

    expect(screen.getByRole("alert")).toHaveTextContent("查詢失敗");
  });

  it("列出未就緒來源的原因與要跑的命令", () => {
    render(<SourceStatusBanner status={status("unavailable", [UNSYNCED])} />);

    expect(screen.getByText(UNSYNCED.detail!)).toBeInTheDocument();
    expect(screen.getByText(UNSYNCED.remedy!)).toBeInTheDocument();
  });

  it("部分未就緒時說明只是涵蓋範圍縮小", () => {
    render(<SourceStatusBanner status={status("degraded", [UNSYNCED, READY])} />);

    expect(screen.getByRole("alert")).toHaveTextContent("部分");
  });

  it("只列未就緒的來源，已就緒的不吵人", () => {
    render(<SourceStatusBanner status={status("degraded", [UNSYNCED, READY])} />);

    expect(screen.getByRole("alert")).toHaveTextContent("taiwan_law");
    expect(screen.getByRole("alert")).not.toHaveTextContent("mock");
  });

  it("沒有補救命令時不顯示空的指示", () => {
    const flaky: SourceReadiness = {
      source: "taiwan_law",
      ready: false,
      detail: "連線逾時",
      remedy: null,
    };

    render(<SourceStatusBanner status={status("unavailable", [flaky])} />);

    expect(screen.getByText("連線逾時")).toBeInTheDocument();
    expect(screen.getByRole("alert")).not.toHaveTextContent("請執行");
  });
});
