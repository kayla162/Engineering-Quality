"""同步行政規則目錄與標準目錄：依每筆的官方網址重讀官方頁面，更新狀態、日期與版次。

    python scripts/sync_catalogs.py              # 讀官方網站並寫回 data/admin_rules.json、data/demo_standards.json
    python scripts/sync_catalogs.py --dry-run    # 只列出會變什麼，不寫檔

建議和全國法規的同步一起排程，之後跑異動檢查，文件引用到的法規變了就會出現在「總覽」：

    python scripts/sync_taiwan_law.py && python scripts/sync_catalogs.py; python scripts/check_regulation_changes.py

（sync_catalogs 有變動時以結束碼 2 結束，所以和 check 之間用分號，不用 &&。）

讀得了的網站與讀法見 backend/app/sources/catalog_sync.py。沒有官方網址的（ISO、ASTM、BSI 擋自動讀取；
無障礙設施設計規範的日期抄自 PDF）列在「需人工查證」。每筆之間停一秒，不對官方網站密集送請求。
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.sources.catalog_sync import SyncResult, fetch, sync_admin_rules, sync_standards  # noqa: E402

CATALOGS = (
    ("行政規則與地方法規", "admin_rules.json", "rules", sync_admin_rules),
    ("標準", "demo_standards.json", "standards", sync_standards),
)


def polite_fetch(url: str) -> bytes:
    time.sleep(1)
    return fetch(url)


def report(title: str, result: SyncResult) -> None:
    print(f"【{title}】變動 {len(result.changed)}、沒變 {len(result.unchanged)}、略過 {len(result.skipped)}")
    for key, changes in result.changed:
        detail = "；".join(f"{field}：{old} → {new}" for field, (old, new) in changes.items())
        print(f"  變動 {key}：{detail}")
    for key, reason in result.skipped:
        print(f"  略過 {key}：{reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="只列出會變什麼，不寫檔")
    args = parser.parse_args()

    changed = 0
    for title, filename, key, sync in CATALOGS:
        path = settings.DATA_DIR / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        result = sync(data[key], fetcher=polite_fetch)
        report(title, result)
        changed += len(result.changed)
        # 沒變的也寫回：每筆的 synced_at 記錄「最近一次確認官方頁面還是這樣」
        if (result.changed or result.unchanged) and not args.dry_run:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print("（--dry-run：沒有寫檔）")
    return 2 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
