"""匯入企業內部文件清單（Excel），整份取代該租戶現有的清單。

    python scripts/import_enterprise_documents.py <清單.xlsx> --tenant <租戶名稱>

只有一個租戶時可以省略 --tenant。格式見 data/templates/企業內部文件清單範本.xlsx；
試用可以匯入假資料 data/samples/enterprise_documents_demo.xlsx。
也可以由租戶管理員在畫面「總覽」上傳，效果相同。

任何一列有錯就整份不匯入，並逐列列出錯誤。匯入後重新分析文件才會用上新清單；
已分析過的文件要看內部文件狀態有沒有變，跑 scripts/check_regulation_changes.py。
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.core.enums import AuditAction  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402
from app.services.enterprise_document_service import (  # noqa: E402
    EnterpriseDocumentService,
    EnterpriseImportError,
    parse_workbook,
)

SYSTEM_USER = "system:import_enterprise_documents"


async def run(path: Path, tenant_name: str | None) -> int:
    try:
        documents = parse_workbook(path.read_bytes())
    except EnterpriseImportError as exc:
        print(f"未匯入：{exc.message}")
        for error in exc.details or []:
            where = f"第 {error['row']} 列：" if error["row"] else ""
            print(f"  - {where}{error['message']}")
        return 1

    try:
        async with get_session_factory()() as session:
            tenants = (
                await session.execute(select(Tenant).where(Tenant.is_active.is_(True)))
            ).scalars().all()
            if tenant_name:
                tenants = [t for t in tenants if t.name == tenant_name]
            if len(tenants) != 1:
                names = "、".join(t.name for t in tenants) or "（無）"
                print(
                    f"找不到租戶「{tenant_name}」" if tenant_name
                    else f"有多個租戶，請用 --tenant 指定：{names}"
                )
                return 1
            tenant = tenants[0]
            count = await EnterpriseDocumentService(session, tenant.id).replace_all(
                documents, SYSTEM_USER
            )
            await AuditService(session).record(
                AuditAction.ENTERPRISE_DOCUMENTS_IMPORTED,
                tenant_id=tenant.id,
                username=SYSTEM_USER,
                detail={"filename": path.name, "total": count},
            )
            await session.commit()
            print(f"已匯入 {count} 份文件到租戶「{tenant.name}」")
    finally:
        await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="匯入企業內部文件清單")
    parser.add_argument("path", type=Path, help="清單 Excel 檔（.xlsx）")
    parser.add_argument("--tenant", help="租戶名稱；只有一個租戶時可省略")
    args = parser.parse_args()
    if not args.path.exists():
        parser.error(f"找不到檔案：{args.path}")
    return asyncio.run(run(args.path, args.tenant))


if __name__ == "__main__":
    sys.exit(main())
