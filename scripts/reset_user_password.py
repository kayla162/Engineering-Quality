"""由部署操作員互動式重設使用者密碼，不會啟用停用帳號。"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


async def reset_password(username: str, password: str) -> None:
    from app.core.db import dispose_engine, get_session_factory
    from app.services.auth_service import AuthService

    try:
        async with get_session_factory()() as session:
            user = await AuthService(session).operator_reset_password(username, password)
            await session.commit()
            print(f"已重設 {user.username} 的密碼；下次登入時必須更改。")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="由部署操作員重設使用者密碼")
    parser.add_argument("--username", required=True, help="使用者登入名稱")
    args = parser.parse_args()
    password = getpass.getpass("新密碼（至少 12 個字元）：")
    confirmation = getpass.getpass("再次輸入新密碼：")
    if password != confirmation:
        parser.error("兩次輸入的密碼不一致")
    try:
        asyncio.run(reset_password(args.username, password))
    except Exception as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
