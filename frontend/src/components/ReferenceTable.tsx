import type { ReferenceItem, ReferenceList } from "../api/types";
import { NEEDS_ATTENTION, TYPE_LABELS, formatPercent } from "../labels";
import { ReviewBadge, StatusBadge } from "./StatusBadge";

export function SummaryBar({ summary }: { summary: ReferenceList["summary"] }) {
  const cells: [string, number, string][] = [
    ["現行有效", summary.confirmed_active, "active"],
    ["已修正", summary.possible_amended, "amended"],
    ["已廢止", summary.possible_repealed, "repealed"],
    ["疑似對應", summary.possible_match, "possible_match"],
    ["查無此法規", summary.not_found, "not_found"],
    ["查詢失敗", summary.unknown, "unknown"],
  ];
  return (
    <>
      <div className="summary">
        {cells.map(([label, value, key]) => (
          <div key={key} className={`summary-cell summary-${key}`}>
            <span className="summary-value">{value}</span>
            <span className="summary-label">{label}</span>
          </div>
        ))}
      </div>
      {/*
        「查詢失敗」幾乎都是法規來源沒就緒造成的。來源修好之後全域橫幅就會消失，
        但這份舊報告仍然滿是查詢失敗——那時候只剩這句話能解釋畫面上看到的東西。
      */}
      {summary.unknown > 0 && (
        <p className="hint">
          其中 {summary.unknown} 筆「查詢失敗」：通常是法規來源尚未就緒，
          系統沒查到答案，不代表該法規不存在。來源就緒後重新分析即可更新這些項目。
        </p>
      )}
    </>
  );
}

export function ReferenceTable({
  items,
  selectedId,
  onSelect,
}: {
  items: ReferenceItem[];
  selectedId: string | null;
  onSelect: (referenceId: string) => void;
}) {
  if (items.length === 0) {
    return <p className="hint">沒有符合條件的法規引用。</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>原始文字</th>
          <th>正規化名稱</th>
          <th>類型</th>
          <th>頁碼</th>
          <th>狀態</th>
          <th>信心</th>
          <th>人工覆核</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.reference_id}
            className={[
              "clickable",
              item.reference_id === selectedId ? "selected" : "",
              NEEDS_ATTENTION.includes(item.status) ? "attention" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onSelect(item.reference_id)}
          >
            <td>
              {item.raw_text}
              {item.article && <span className="hint"> {item.article}</span>}
            </td>
            <td>{item.normalized_name ?? "—"}</td>
            <td>{TYPE_LABELS[item.regulation_type] ?? item.regulation_type}</td>
            <td>{item.page ?? "—"}</td>
            <td>
              <StatusBadge status={item.status} tentative={item.is_tentative} />
            </td>
            <td>{formatPercent(item.match_confidence)}</td>
            <td>
              <ReviewBadge status={item.review_status} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
