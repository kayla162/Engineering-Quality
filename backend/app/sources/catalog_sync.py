"""行政規則目錄（data/admin_rules.json）與標準目錄（data/demo_standards.json）的自動同步。

兩份目錄原本是 2026-11 人工查證的快照：法規修正、廢止，標準改版，目錄都不會跟著變。
這裡依每筆的官方網址（`source_url`）重新讀官方頁面，更新狀態與日期；變了什麼就回報，
由 scripts/sync_catalogs.py 寫回目錄。之後跑 scripts/check_regulation_changes.py，
文件引用到的法規就會出現在「法規異動」——和全國法規的同步是同一條路。

讀得了的官方網站（2026-11 實測，頁面都是「標籤：值」的寫法，日期是民國年）：

- 工程會法規資料庫 lawweb.pcc.gov.tw、勞動部 laws.mol.gov.tw：
  「法規名稱：」「公發布日：」／「公(發)布日期：」「修正日期：」；Big5 編碼
- 新北市法規查詢系統 web.law.ntpc.gov.tw：同上，「公發布時間：」；廢止的有「廢止時間：」
- 標準檢驗局 CNS 網路服務系統 www.cnsonline.com.tw：「標準名稱：」「狀態：現行標準」
  「公告日期：059/05/05」「修訂日期：114/12/19」；UTF-8

ISO、ASTM、BSI 官網擋自動讀取，那幾筆不自動同步（`source_url` 留空），回報「需人工查證」。
讀不出必要欄位時**不改**那一筆、回報原因——讀錯比沒讀更糟。
"""

import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date

USER_AGENT = "EngineeringQualityCatalogSync/1.0 (+https://github.com/kayla162/Engineering-Quality)"
TIMEOUT = 30

_ROC_DATE = re.compile(r"民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_SLASH_DATE = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


@dataclass(frozen=True)
class RegulationPage:
    name: str
    issued_date: str | None
    last_amended_date: str | None
    repealed_date: str | None


@dataclass(frozen=True)
class StandardPage:
    title: str
    status: str
    #: 最近一次修訂（沒有修訂就是公告）的日期
    edition_date: str


@dataclass
class SyncResult:
    #: (id 或編號, {欄位: (舊, 新)})
    changed: list[tuple[str, dict]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    #: (id 或編號, 原因)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def page_text(raw: bytes) -> str:
    """HTML -> 一行一段的純文字。官方網站有 Big5 也有 UTF-8，看 meta 宣告。"""
    head = raw[:4000].lower()
    encoding = "utf-8" if b"utf-8" in head else "cp950"
    text = _BLOCK.sub(" ", raw.decode(encoding, errors="replace"))
    import html

    text = html.unescape(_TAG.sub("\n", text))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _after(label: str, text: str) -> str | None:
    """「標籤：」後面的值（同一行，或標籤自成一行時的下一行）。"""
    match = re.search(rf"{label}[：:]\s*([^\n]*)\n?([^\n]*)", text)
    if not match:
        return None
    value = match.group(1).strip() or match.group(2).strip()
    return value or None


def _roc(value: str | None) -> str | None:
    if not value:
        return None
    match = _ROC_DATE.search(value) or _SLASH_DATE.search(value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year + 1911, month, day).isoformat()


def parse_regulation_page(text: str) -> RegulationPage | None:
    """工程會／勞動部／新北市法規頁。讀不到法規名稱就回 None。"""
    name = _after("法規名稱", text)
    if not name:
        return None
    issued = _roc(_after(r"公\(?發\)?布(?:日期|時間|日)", text))
    amended = _roc(_after(r"修正(?:日期|時間)", text))
    repealed = _roc(_after(r"廢止(?:日期|時間)", text))
    return RegulationPage(name=name, issued_date=issued, last_amended_date=amended, repealed_date=repealed)


def parse_standard_page(text: str) -> StandardPage | None:
    """CNS 標準頁。名稱、狀態、日期少一樣就回 None。"""
    title, status = _after("標準名稱", text), _after("狀態", text)
    edition = _roc(_after("修訂日期", text)) or _roc(_after("公告日期", text))
    if not (title and status and edition):
        return None
    return StandardPage(title=title, status="REPEALED" if "廢止" in status else "ACTIVE", edition_date=edition)


def _tls_context():
    """照常驗證憑證鏈與主機名稱，只關掉 Python 3.13 起預設的 X.509 嚴格模式：工程會、新北市、
    標準檢驗局的政府憑證鏈缺「Subject Key Identifier」擴充欄位，嚴格模式會一律拒絕（2026-11 實測）。"""
    import ssl

    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=_tls_context()) as response:  # noqa: S310 - 只讀目錄裡寫明的官方網址
        return response.read()


def sync_admin_rules(rules: list[dict], fetcher=fetch, today: str | None = None) -> SyncResult:
    """就地更新 rules（admin_rules.json 的 "rules"），回傳變了什麼。"""
    result = SyncResult()
    today = today or date.today().isoformat()
    for rule in rules:
        url = rule.get("source_url")
        if not url:
            result.skipped.append((rule["id"], "沒有可自動讀取的官方網址，需人工查證"))
            continue
        try:
            page = parse_regulation_page(page_text(fetcher(url)))
        except Exception as exc:  # 網路錯誤、逾時：這一筆不動
            result.skipped.append((rule["id"], f"讀取失敗：{exc}"))
            continue
        if page is None:
            result.skipped.append((rule["id"], "官方頁面讀不出法規名稱（版面可能改了）"))
            continue

        new = {
            "status": "REPEALED" if page.repealed_date else rule["status"],
            "last_amended_date": page.repealed_date or page.last_amended_date or rule.get("last_amended_date"),
            "issued_date": page.issued_date or rule.get("issued_date"),
            "name": page.name,
        }
        changes = {key: (rule.get(key), value) for key, value in new.items() if rule.get(key) != value}
        if "name" in changes and rule["name"] not in rule.get("aliases", []):
            # 更名：舊名留成別名，文件裡寫舊名的引用照樣查得到
            rule.setdefault("aliases", []).append(rule["name"])
        for key, (_old, value) in changes.items():
            rule[key] = value
        rule["synced_at"] = today
        (result.changed.append((rule["id"], changes)) if changes else result.unchanged.append(rule["id"]))
    return result


def sync_standards(standards: list[dict], fetcher=fetch, today: str | None = None) -> SyncResult:
    """就地更新 standards（demo_standards.json 的 "standards"）。版次寫年份，與原本的欄位一致。"""
    result = SyncResult()
    today = today or date.today().isoformat()
    for record in standards:
        url = record.get("source_url")
        if not url:
            result.skipped.append((record["number"], "官網擋自動讀取，需人工查證"))
            continue
        try:
            page = parse_standard_page(page_text(fetcher(url)))
        except Exception as exc:
            result.skipped.append((record["number"], f"讀取失敗：{exc}"))
            continue
        if page is None:
            result.skipped.append((record["number"], "官方頁面讀不出名稱、狀態或日期（版面可能改了）"))
            continue

        new = {"status": page.status, "latest_edition": page.edition_date[:4], "edition_date": page.edition_date}
        changes = {key: (record.get(key), value) for key, value in new.items() if record.get(key) != value}
        for key, (_old, value) in changes.items():
            record[key] = value
        record["synced_at"] = today
        (result.changed.append((record["number"], changes)) if changes else result.unchanged.append(record["number"]))
    return result
