import type { Job } from "../api/types";
import { STEP_LABELS } from "../labels";

export function JobProgress({ job }: { job: Job }) {
  if (job.status === "FAILED") {
    return (
      <div className="job job-failed">
        <strong>分析失敗</strong>
        <p className="error">{job.error_message ?? "未知錯誤"}</p>
      </div>
    );
  }

  if (job.status === "COMPLETED") {
    return <div className="job job-done">分析完成</div>;
  }

  const step = job.current_step ? (STEP_LABELS[job.current_step] ?? job.current_step) : "準備中";
  return (
    <div className="job">
      <div className="progress-track">
        <div className="progress-bar" style={{ width: `${job.progress}%` }} />
      </div>
      <span>
        {step}（{job.progress}%）
      </span>
    </div>
  );
}
