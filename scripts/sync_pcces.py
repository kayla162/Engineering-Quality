"""從工程會技術雲同步「公共工程共通性工項施工綱要規範」目錄到本地。

    python scripts/sync_pcces.py

為什麼是「同步」而不是即時查詢：
    這支 endpoint 沒有公開文件（見下方警告），隨時可能改。同步成本地目錄的話，
    壞掉的時候是在維運手上大聲失敗，而不是在客戶跑分析到一半時才炸。
    315 章的目錄只有幾十 KB，同步成本可以忽略。

⚠️ 這不是工程會公告的 Open API
    公告的「公共工程應用 Open API」(pcic.pcc.gov.tw/pwc-web/service/api001) 只有兩支
    endpoint：取得 Token 與「決標價格之 XML 驗證」，沒有任何法規或規範資料。
    這裡用的是技術雲「規範及編碼文件下載」頁面 (tec0304) 背後的 endpoint，
    無需認證，但沒有文件、沒有版本承諾。它改了就會同步失敗，
    PccesSource.readiness() 會讓前端亮出未就緒橫幅，不會安靜地給錯答案。

已於 2026-09 實際查證：
    POST /pwc-web/api/service/tec-fundamental-codes/getSearchList
    body: {"tecCode": "", "cname": "", "currentPage": 0}
    回傳 Spring Page：{"content": [...], "totalElements": 315, "totalPages": 16}
    每頁固定 20 筆（size 參數無效，只能靠 currentPage 翻頁）
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402

API_URL = "https://pcic.pcc.gov.tw/pwc-web/api/service/tec-fundamental-codes/getSearchList"
CATALOGUE_URL = "https://pcic.pcc.gov.tw/pwc-web/service/tec0304"
ATTRIBUTION = "資料來源：行政院公共工程委員會 公共工程雲端服務網（技術雲）"

def _ssl_context() -> ssl.SSLContext:
    """政府網站的憑證少了 Subject Key Identifier，過不了 Python 3.13 的嚴格檢查。

    Python 3.13 起 create_default_context() 預設帶 VERIFY_X509_STRICT（RFC 5280 嚴格模式），
    而 pcic.pcc.gov.tw 的憑證鏈不符合，會直接 CERTIFICATE_VERIFY_FAILED。
    這裡只關掉那個嚴格旗標——**憑證鏈與主機名稱仍然完整驗證**（verify_mode 維持
    CERT_REQUIRED）。不要改成 CERT_NONE，那才是真的把加密驗證關掉。
    """
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


#: 每頁之間停一下，不要對政府網站連續猛打
PAGE_DELAY_SECONDS = 0.3
#: 目錄現況約 16 頁；設上限避免對方回傳異常時無限翻頁
MAX_PAGES = 100


def fetch_page(page: int, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"tecCode": "", "cname": "", "currentPage": page}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def to_chapter(record: dict) -> dict | None:
    """官方欄位 -> 目錄項目。只留比對需要的欄位，規範全文留在官網。

    sample     章碼（5 位）
    cname      章名
    fEdition   規範版次，正常是 "8.0"；已刪除的章節這裡會是「本章已刪除」
    cEdition   工項編碼版次
    """
    code = str(record.get("sample") or "").strip()
    name = str(record.get("cname") or "").strip()
    if not code or not name:
        return None

    files = record.get("viewIdFileList") or []
    return {
        "code": code,
        "name": name,
        "edition": str(record.get("fEdition") or "").strip(),
        "code_edition": str(record.get("cEdition") or "").strip(),
        "updated_at": files[0].get("createTime") if files else None,
    }


def build_index() -> dict:
    chapters: dict[str, dict] = {}
    expected: int | None = None
    page = 0

    while page < MAX_PAGES:
        payload = fetch_page(page)
        if expected is None:
            expected = payload.get("totalElements")
            print(f"  官方回報共 {expected} 章、{payload.get('totalPages')} 頁")

        for record in payload.get("content", []):
            chapter = to_chapter(record)
            if chapter is not None:
                chapters.setdefault(chapter["code"], chapter)

        print(f"  第 {page + 1} 頁：累計 {len(chapters)} 章", end="\r", flush=True)
        if payload.get("last") or not payload.get("content"):
            break
        page += 1
        time.sleep(PAGE_DELAY_SECONDS)

    print()
    if not chapters:
        raise RuntimeError("目錄是空的——endpoint 可能已經改了，索引不覆蓋")
    if expected is not None and len(chapters) != expected:
        # 只警告不中斷：少幾章仍然比完全沒有目錄好，但要讓維運看得見
        print(f"  ⚠ 官方說有 {expected} 章，實際收到 {len(chapters)} 章", file=sys.stderr)

    return {
        "source": "pcces",
        "attribution": ATTRIBUTION,
        "api_url": API_URL,
        "catalogue_url": CATALOGUE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "expected_count": expected,
        "count": len(chapters),
        "chapters": sorted(chapters.values(), key=lambda c: c["code"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="同步公共工程施工綱要規範目錄")
    parser.add_argument(
        "--output", type=Path, default=settings.PCCES_INDEX_PATH, help="目錄輸出路徑"
    )
    args = parser.parse_args()

    print("同步公共工程施工綱要規範目錄（工程會技術雲）")
    try:
        index = build_index()
    except (urllib.error.URLError, RuntimeError, ValueError) as exc:
        print(f"\n同步失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
        print("目錄維持原狀，系統會繼續使用既有資料。", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    size_kb = args.output.stat().st_size / 1024
    print(f"\n完成：{index['count']} 章 -> {args.output}（{size_kb:.0f} KB）")
    print(ATTRIBUTION)
    print("\n下一步：在 .env 的 REGULATION_SOURCES 加上 pcces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
