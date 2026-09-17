"""從全國法規資料庫 Open API 同步法規清單到本地索引。

    python scripts/sync_taiwan_law.py

為什麼是「同步」而不是「即時查詢」：
    法務部的 Open API 只提供**整包 ZIP 下載**（法律 6MB / 命令 26MB），
    沒有「查單一法規」的 endpoint。如果每比對一筆引用就打一次 API，
    等於每筆都下載 31MB，完全不可行。
    因此改成定期同步成本地索引，TaiwanLawSource 再從索引查詢。

官方 API（已於 2026-09 實際查證）：
    GET https://law.moj.gov.tw/api/Ch/Law/JSON     -> ChLaw.json.zip    法律 約 1,346 筆
    GET https://law.moj.gov.tw/api/Ch/Order/JSON   -> ChOrder.json.zip  命令 約 10,447 筆
    GET https://law.moj.gov.tw/api/En/Law/JSON     -> EngLaw.json.zip   英譯法律
    GET https://law.moj.gov.tw/api/En/Order/JSON   -> EngOrder.json.zip 英譯命令

    回傳的是 ZIP（不是 JSON body），內含 {名稱}.json + schema.csv + manifest.csv。
    JSON 結構：{"UpdateDate": "...", "Laws": [ ... ]}

授權：政府資料開放授權條款第 1 版（GODL v1.0，等同 CC BY 4.0），需註明出處。
"""

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402

API_BASE = "https://law.moj.gov.tw/api"
ATTRIBUTION = "資料來源：法務部全國法規資料庫（政府資料開放授權條款第 1 版）"

# API 路徑 -> (ZIP 內的 JSON 檔名, 我們給的層級標籤)
DATASETS: dict[str, tuple[str, str]] = {
    "Ch/Law": ("ChLaw.json", "法律"),
    "Ch/Order": ("ChOrder.json", "命令"),
}

# LawURL 形如 https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0000001
_PCODE = re.compile(r"pcode=([A-Z0-9]+)", re.IGNORECASE)

# 只保留比對需要的欄位。條文全文留在原始 ZIP 裡，Phase 2 做 RAG 時再處理，
# 不放進索引（否則索引會膨脹到 30MB 以上）。
INDEX_FIELDS = (
    "external_id", "name", "level", "category", "url",
    "modified_date", "effective_date", "effective_note", "abandoned", "eng_name",
)


def download(dataset: str, timeout: int = 300) -> bytes:
    url = f"{API_BASE}/{dataset}/JSON"
    print(f"  下載 {url} ...", end="", flush=True)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read()
    print(f" {len(payload) / 1024 / 1024:.1f} MB")
    return payload


def parse_zip(payload: bytes, json_name: str) -> tuple[str, list[dict]]:
    """回傳 (UpdateDate, 法規清單)。"""
    archive = zipfile.ZipFile(io.BytesIO(payload))
    data = json.loads(archive.read(json_name).decode("utf-8-sig"))
    return data.get("UpdateDate", ""), data.get("Laws", [])


def to_index_entry(record: dict, level_label: str) -> dict | None:
    """官方欄位 -> 本地索引欄位。欄位名稱依 ZIP 內的 schema.csv。"""
    url = record.get("LawURL", "") or ""
    pcode = _PCODE.search(url)
    name = (record.get("LawName") or "").strip()
    if not name or not pcode:
        return None  # 沒有名稱或沒有官方識別碼的資料無法比對，直接略過

    return {
        "external_id": pcode.group(1).upper(),
        "name": name,
        "level": record.get("LawLevel") or level_label,
        "category": record.get("LawCategory") or "",
        "url": url,
        "modified_date": (record.get("LawModifiedDate") or "").strip(),
        "effective_date": (record.get("LawEffectiveDate") or "").strip(),
        "effective_note": (record.get("LawEffectiveNote") or "").strip(),
        # 官方以 LawAbandonNote == "廢" 表示廢止，其餘為空字串
        "abandoned": (record.get("LawAbandonNote") or "").strip() == "廢",
        "eng_name": (record.get("EngLawName") or "").strip(),
    }


def build_index(keep_raw: bool) -> dict:
    cache_dir = settings.DATA_DIR / "taiwan_law_cache"
    entries: list[dict] = []
    update_dates: dict[str, str] = {}
    seen: set[str] = set()

    for dataset, (json_name, level_label) in DATASETS.items():
        payload = download(dataset)
        if keep_raw:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{json_name}.zip").write_bytes(payload)

        update_date, records = parse_zip(payload, json_name)
        update_dates[dataset] = update_date

        kept = 0
        for record in records:
            entry = to_index_entry(record, level_label)
            if entry is None or entry["external_id"] in seen:
                continue
            seen.add(entry["external_id"])
            entries.append(entry)
            kept += 1
        print(f"  {dataset}: {len(records)} 筆，收錄 {kept} 筆（UpdateDate {update_date}）")

    entries.sort(key=lambda e: e["name"])
    return {
        "source": "taiwan_law",
        "attribution": ATTRIBUTION,
        "licence": "政府資料開放授權條款第 1 版 (GODL v1.0)",
        "api_base": API_BASE,
        "datasets": list(DATASETS),
        "update_dates": update_dates,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "fields": list(INDEX_FIELDS),
        "regulations": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="同步全國法規資料庫到本地索引")
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.TAIWAN_LAW_INDEX_PATH,
        help="索引輸出路徑",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="保留下載的原始 ZIP 到 data/taiwan_law_cache/（稽核與 Phase 2 RAG 會用到）",
    )
    args = parser.parse_args()

    print("同步全國法規資料庫（法務部 Open API）")
    try:
        index = build_index(keep_raw=args.keep_raw)
    except Exception as exc:
        print(f"\n同步失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
        print("索引維持原狀，系統會繼續使用既有資料。", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"\n完成：{index['count']} 筆 -> {args.output}（{size_mb:.1f} MB）")
    print(ATTRIBUTION)
    print("\n下一步：在 .env 設定 REGULATION_SOURCES=taiwan_law（或 taiwan_law,mock）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
