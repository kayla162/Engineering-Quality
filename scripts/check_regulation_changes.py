"""法規異動監控：對每個啟用中的租戶檢查一輪，給排程（cron / 工作排程器）用。

    python scripts/check_regulation_changes.py

建議放在同步官方資料之後跑——官方資料庫大約每週更新一次：

    python scripts/sync_taiwan_law.py && python scripts/check_regulation_changes.py

只檢查「有文件引用到」的法規。偵測到的異動會出現在畫面的「總覽」，
引用的狀態不會被自動改掉，需要人看過後重新分析受影響的文件。
有新異動時以結束碼 2 結束，方便排程接通知；沒有異動是 0。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.core.enums import AuditAction  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402
from app.services.regulation_change_service import RegulationChangeService  # noqa: E402

SYSTEM_USER = "system:check_regulation_changes"


async def main() -> int:
    total_changed = 0
    try:
        async with get_session_factory()() as session:
            tenants = (
                await session.execute(select(Tenant).where(Tenant.is_active.is_(True)))
            ).scalars().all()
            for tenant in tenants:
                summary = await RegulationChangeService(session, tenant.id).check()
                await AuditService(session).record(
                    AuditAction.REGULATION_CHANGES_CHECKED,
                    tenant_id=tenant.id,
                    username=SYSTEM_USER,
                    detail={
                        "checked": summary.checked,
                        "changed": summary.changed,
                        "skipped": len(summary.skipped),
                    },
                )
                await session.commit()
                total_changed += summary.changed
                print(
                    f"[{tenant.name}] 檢查 {summary.checked} 部、新異動 {summary.changed} 筆、"
                    f"略過 {len(summary.skipped)} 部"
                )
                for change in summary.new_changes:
                    await session.refresh(change, ["regulation"])
                    print(f"  - {change.regulation.name}：{change.changes}")
                for row in summary.skipped:
                    print(f"  ! 略過 {row['name']}：{row['reason']}")
    finally:
        await dispose_engine()
    return 2 if total_changed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
