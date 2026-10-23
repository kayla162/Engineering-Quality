import { describe, expect, it } from "vitest";

import { formatDateTime } from "./labels";

describe("formatDateTime", () => {
  it("沒有時區標記的時間當成 UTC（SQLite 回來的格式）", () => {
    expect(formatDateTime("2026-10-23T20:20:09")).toBe(formatDateTime("2026-10-23T20:20:09Z"));
  });

  it("有時區標記就照標記", () => {
    expect(formatDateTime("2026-10-24T04:20:09+08:00")).toBe(formatDateTime("2026-10-23T20:20:09Z"));
  });

  it("空值顯示破折號", () => {
    expect(formatDateTime(null)).toBe("—");
  });
});
