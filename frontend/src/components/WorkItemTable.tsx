import type { WorkItem } from "../api/types";

export function WorkItemSummary({
  total,
  withSpecChapter,
}: {
  total: number;
  withSpecChapter: number;
}) {
  const missing = total - withSpecChapter;
  const cells: [string, number, string][] = [
    ["工項總數", total, "total"],
    ["對到章節", withSpecChapter, "matched"],
    ["未對到", missing, "missing"],
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
        對不到章節是正常結果，不是故障。共通性工項施工綱要規範只涵蓋 315 個共通章節，
        各機關自訂的專業工項本來就不在裡面。不解釋的話，一整欄空白看起來就像系統壞了
        ——跟法規那邊「查詢失敗」要附說明是同一個理由。
      */}
      {missing > 0 && (
        <p className="hint">
          其中 {missing} 筆沒有對到施工綱要規範章節：多數是沒有計價代碼，或代碼屬於
          各機關自訂的專業工項——共通性工項目錄不涵蓋這些。這不代表該工項沒有規範可依，
          只代表系統沒辦法自動指出是哪一章。
        </p>
      )}
    </>
  );
}

export function WorkItemTable({
  items,
  onlyMissing,
  onOnlyMissingChange,
}: {
  items: WorkItem[];
  onlyMissing: boolean;
  onOnlyMissingChange: (value: boolean) => void;
}) {
  if (items.length === 0) {
    return (
      <p className="hint">
        這個專案還沒有工項。先把標單掛上去（角色選「標單」），再按「從標單建立工項」。
      </p>
    );
  }

  const rows = onlyMissing ? items.filter((item) => item.spec_chapter === null) : items;

  return (
    <>
      <label className="filter-toggle">
        <input
          type="checkbox"
          checked={onlyMissing}
          onChange={(event) => onOnlyMissingChange(event.target.checked)}
        />
        只看未對到章節的工項
      </label>

      <table>
        <thead>
          <tr>
            <th>項次</th>
            <th>工程項目</th>
            <th>單位</th>
            <th>數量</th>
            <th>計價代碼</th>
            <th>施工綱要規範</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.work_item_id} className={item.spec_chapter ? "" : "attention"}>
              <td className="nowrap">{item.item_no}</td>
              <td>{item.name}</td>
              <td>{item.unit}</td>
              <td>{item.quantity}</td>
              <td className="nowrap">{item.cost_code ?? "—"}</td>
              <td>
                {item.spec_chapter ? (
                  <>
                    <span className="chapter-code">{item.spec_chapter.code}</span>{" "}
                    {item.spec_chapter.name}
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
