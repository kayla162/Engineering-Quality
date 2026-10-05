import { vi } from "vitest";

/** 用路徑前綴回傳假回應，順便驗證前端真的打了那個路徑。
 *
 * 比對順序是「最長前綴優先」，否則 `/api/projects` 會把 `/api/projects/x/work-items`
 * 一起吃掉，測試就看不出前端到底打了哪一支。
 */
export function stubApi(routes: Record<string, unknown>) {
  const prefixes = Object.keys(routes).sort((a, b) => b.length - a.length);
  const calls: string[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      const path = prefixes.find((prefix) => url.startsWith(prefix));
      if (path === undefined) throw new Error(`測試沒有準備這個路徑：${url}`);
      return new Response(JSON.stringify(routes[path]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  return calls;
}
