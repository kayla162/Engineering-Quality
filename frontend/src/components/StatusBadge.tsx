import type { RegulationStatus, ReviewStatus } from "../api/types";
import { REVIEW_LABELS, STATUS_LABELS } from "../labels";

export function StatusBadge({
  status,
  tentative,
}: {
  status: RegulationStatus;
  tentative?: boolean;
}) {
  return (
    <span className={`badge badge-${status.toLowerCase()}`}>
      {STATUS_LABELS[status]}
      {/* NOT_FOUND 與 POSSIBLE_MATCH 的字面已經表達不確定，不再重複標示 */}
      {tentative && status !== "NOT_FOUND" && status !== "POSSIBLE_MATCH" ? "（疑似）" : ""}
    </span>
  );
}

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  return <span className={`badge review-${status.toLowerCase()}`}>{REVIEW_LABELS[status]}</span>;
}
