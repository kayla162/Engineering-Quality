"""互動式建立部署中的第一位租戶管理員。資料庫須先完成 Alembic migration。"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


async def bootstrap(tenant_name: str, username: str, password: str) -> None:
    try:
        async with get_session_factory()() as session:
            user = await AuthService(session).bootstrap_admin(tenant_name, username, password)
            await session.commit()
            print(f"已建立管理員 {user.username}（租戶：{tenant_name}）")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="建立首位租戶管理員")
    parser.add_argument("--tenant-name", required=True, help="租戶顯示名稱")
    parser.add_argument("--username", required=True, help="管理員登入名稱")
    args = parser.parse_args()
    password = getpass.getpass("管理員密碼（至少 12 個字元）：")
    confirmation = getpass.getpass("再次輸入密碼：")
    if password != confirmation:
        parser.error("兩次輸入的密碼不一致")
    try:
        asyncio.run(bootstrap(args.tenant_name, args.username, password))
    except Exception as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
