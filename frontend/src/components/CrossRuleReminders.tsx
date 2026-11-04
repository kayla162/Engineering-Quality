import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { CrossRuleReminder } from "../api/types";

/** 法規雙重規範提醒：同一個構件要同時滿足兩部規定。目錄是示範，每條寫明出處；不影響檢核結果。 */
export function CrossRuleReminders({ projectId }: { projectId: string }) {
  const [reminders, setReminders] = useState<CrossRuleReminder[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setReminders(null);
    api
      .getCrossRuleReminders(projectId)
      // 舊版後端沒有這支 API：回來的不是陣列就當作沒有提醒
      .then((data) => !cancelled && setReminders(Array.isArray(data) ? data : []))
      .catch(() => !cancelled && setReminders([]));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (!reminders || reminders.length === 0) return null;
  return (
    <section className="card">
      <h3>法規雙重規範提醒（示範）</h3>
      <p className="hint">同一個構件要同時滿足兩部以上規定時提醒。只是提醒，不是檢核結果；未寫出處的條號與數值未查證。</p>
      <ul>
        {reminders.map((reminder) => (
          <li key={reminder.rule_id}>
            <strong>{reminder.title}</strong>（{reminder.regulations.join("、")}）：{reminder.note}
            <div className="hint">
              出處：{reminder.provenance}。觸發 {reminder.matches} 項，例如：{reminder.evidence.join("；")}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
