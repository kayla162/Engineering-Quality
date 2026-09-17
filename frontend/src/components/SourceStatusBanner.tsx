import type { SourcesStatus } from "../api/types";
import { SOURCE_WARNINGS } from "../labels";

/**
 * 法規來源未就緒時的全域提示。
 *
 * 官方法規索引是同步腳本產生的本地檔案，要先跑過才有。沒跑的話分析照樣會跑完，
 * 但每一筆引用都會變成「查詢失敗」。沒有這個橫幅，使用者只會看到滿頁查詢失敗，
 * 卻不知道原因，也不知道下一步該做什麼。
 *
 * 來源都就緒時完全不渲染——正常狀態不該佔畫面。
 */
export function SourceStatusBanner({ status }: { status: SourcesStatus | null }) {
  // null = 還在載入（或這次載不到）。這種時候安靜，不要用問號嚇人。
  if (status === null || status.status === "ok") return null;

  const warning = SOURCE_WARNINGS[status.status];
  const unready = status.sources.filter((source) => !source.ready);

  return (
    <div className={`banner banner-${status.status}`} role="alert">
      <strong className="banner-headline">{warning.headline}</strong>
      <p>{warning.consequence}</p>
      <ul className="banner-sources">
        {unready.map((source) => (
          <li key={source.source}>
            <span className="badge source">{source.source}</span>
            <span>{source.detail}</span>
            {/* 沒有命令可跑時就不要印一個空的指示 */}
            {source.remedy && (
              <span className="banner-remedy">
                請執行：<code>{source.remedy}</code>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
