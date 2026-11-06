"""行政規則與標準目錄的自動同步（app/sources/catalog_sync.py）。

頁面是照官方網站版面縮成的最小 HTML（2026-11 實測：工程會、勞動部、新北市是 Big5，CNS 是 UTF-8），
不打網路。
"""

from app.sources.catalog_sync import (
    page_text,
    parse_regulation_page,
    parse_standard_page,
    sync_admin_rules,
    sync_standards,
)


def big5_page(fields: list[tuple[str, str]]) -> bytes:
    rows = "".join(f"<tr><th>{label}：</th><td>{value}</td></tr>" for label, value in fields)
    html = f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=big5"></head><body><table>{rows}</table></body></html>'
    return html.encode("cp950")


def cns_page(title: str, status: str, announced: str, revised: str | None) -> bytes:
    revised_row = f"<li>修訂日期：{revised}</li>" if revised else ""
    html = (
        '<html><head><meta charset="utf-8"></head><body><ul>'
        f"<li>標準總號：CNS3090</li><li>標準名稱：{title}</li><li>狀態：{status}</li>"
        f"<li>公告日期：{announced}</li>{revised_row}</ul></body></html>"
    )
    return html.encode("utf-8")


PCC = big5_page([("法規名稱", "公共工程施工品質管理作業要點"), ("公發布日", "民國 85 年 12 月 13 日"), ("修正日期", "民國 112 年 05 月 11 日")])
NTPC_REPEALED = big5_page([("法規名稱", "新北市營建工程剩餘土石方處理及營建混合物資源處理場設置管理要點"), ("廢止時間", "民國 115 年 09 月 08 日")])


class TestParsing:
    def test_a_big5_regulation_page(self):
        page = parse_regulation_page(page_text(PCC))
        assert (page.name, page.issued_date, page.last_amended_date, page.repealed_date) == (
            "公共工程施工品質管理作業要點", "1996-12-13", "2023-05-11", None,
        )

    def test_a_repealed_local_rule(self):
        assert parse_regulation_page(page_text(NTPC_REPEALED)).repealed_date == "2026-09-08"

    def test_a_cns_page_uses_the_revision_date(self):
        page = parse_standard_page(page_text(cns_page("預拌混凝土", "現行標準", "059/05/05", "114/12/19")))
        assert (page.title, page.status, page.edition_date) == ("預拌混凝土", "ACTIVE", "2025-12-19")

    def test_a_never_revised_standard_uses_the_announcement_date(self):
        page = parse_standard_page(page_text(cns_page("鋼管施工架", "現行標準", "115/06/09", None)))
        assert page.edition_date == "2026-06-09"

    def test_a_withdrawn_standard(self):
        assert parse_standard_page(page_text(cns_page("舊標準", "廢止標準", "090/01/01", None))).status == "REPEALED"

    def test_a_page_without_the_labels_is_not_guessed(self):
        assert parse_regulation_page(page_text(b"<html><body>System maintenance</body></html>")) is None
        assert parse_standard_page(page_text(b"<html><body>Not found</body></html>")) is None


def rule(**fields) -> dict:
    base = {"id": "AR-1", "name": "公共工程施工品質管理作業要點", "aliases": [], "status": "ACTIVE",
            "issued_date": "1996-12-13", "last_amended_date": "2020-01-01", "source_url": "https://x/1"}
    return base | fields


class TestSyncAdminRules:
    def test_an_amendment_updates_the_date(self):
        rules = [rule()]
        result = sync_admin_rules(rules, fetcher=lambda url: PCC, today="2026-12-01")
        assert result.changed == [("AR-1", {"last_amended_date": ("2020-01-01", "2023-05-11")})]
        assert rules[0]["last_amended_date"] == "2023-05-11" and rules[0]["synced_at"] == "2026-12-01"

    def test_a_repeal_marks_the_rule_repealed(self):
        rules = [rule(name="新北市營建工程剩餘土石方處理及營建混合物資源處理場設置管理要點")]
        sync_admin_rules(rules, fetcher=lambda url: NTPC_REPEALED)
        assert rules[0]["status"] == "REPEALED" and rules[0]["last_amended_date"] == "2026-09-08"

    def test_a_rename_keeps_the_old_name_as_an_alias(self):
        rules = [rule(name="施工品質管理作業要點")]
        sync_admin_rules(rules, fetcher=lambda url: PCC)
        assert rules[0]["name"] == "公共工程施工品質管理作業要點"
        assert "施工品質管理作業要點" in rules[0]["aliases"]

    def test_unchanged_rules_are_reported_as_unchanged(self):
        result = sync_admin_rules([rule(last_amended_date="2023-05-11")], fetcher=lambda url: PCC)
        assert result.unchanged == ["AR-1"] and not result.changed

    def test_failures_leave_the_record_alone(self):
        def broken(url):
            raise TimeoutError("timed out")

        rules = [rule(), rule(id="AR-2", source_url=""), rule(id="AR-3")]
        result = sync_admin_rules(rules[:2], fetcher=broken)
        assert [key for key, _ in result.skipped] == ["AR-1", "AR-2"]
        assert rules[0]["last_amended_date"] == "2020-01-01" and "synced_at" not in rules[0]
        layout_changed = sync_admin_rules([rules[2]], fetcher=lambda url: b"<html>maintenance</html>")
        assert "版面" in layout_changed.skipped[0][1]


class TestSyncStandards:
    def test_a_revision_moves_the_edition(self):
        standards = [{"number": "CNS 3090", "latest_edition": "2022", "status": "ACTIVE", "source_url": "https://x/cns"}]
        result = sync_standards(standards, fetcher=lambda url: cns_page("預拌混凝土", "現行標準", "059/05/05", "114/12/19"))
        assert standards[0]["latest_edition"] == "2025" and standards[0]["edition_date"] == "2025-12-19"
        assert ("latest_edition", ("2022", "2025")) in result.changed[0][1].items()

    def test_standards_without_an_official_page_need_manual_checks(self):
        result = sync_standards([{"number": "ISO 9001", "latest_edition": "2026", "status": "ACTIVE", "source_url": ""}])
        assert result.skipped == [("ISO 9001", "官網擋自動讀取，需人工查證")]


def test_certificates_are_still_verified():
    """只關掉 X.509 嚴格模式（政府憑證缺 Subject Key Identifier），憑證鏈與主機名稱照樣驗證。"""
    import ssl

    from app.sources.catalog_sync import _tls_context

    context = _tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert not context.verify_flags & ssl.VERIFY_X509_STRICT
