import type { ReferenceFilters, RegulationStatus, ReviewStatus } from "../api/types";
import { REVIEW_LABELS, STATUS_LABELS } from "../labels";

export function FilterBar({
  filters,
  onChange,
}: {
  filters: ReferenceFilters;
  onChange: (filters: ReferenceFilters) => void;
}) {
  return (
    <div className="filters">
      <label>
        狀態
        <select
          value={filters.status ?? ""}
          onChange={(event) =>
            onChange({ ...filters, status: event.target.value as RegulationStatus | "" })
          }
        >
          <option value="">全部</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <label>
        人工覆核
        <select
          value={filters.review_status ?? ""}
          onChange={(event) =>
            onChange({ ...filters, review_status: event.target.value as ReviewStatus | "" })
          }
        >
          <option value="">全部</option>
          {Object.entries(REVIEW_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <label>
        信心下限
        <select
          value={filters.min_confidence ?? ""}
          onChange={(event) =>
            onChange({
              ...filters,
              min_confidence: event.target.value === "" ? "" : Number(event.target.value),
            })
          }
        >
          <option value="">不限</option>
          <option value="0.9">90%</option>
          <option value="0.7">70%</option>
          <option value="0.5">50%</option>
        </select>
      </label>

      <button type="button" className="link" onClick={() => onChange({})}>
        清除篩選
      </button>
    </div>
  );
}
