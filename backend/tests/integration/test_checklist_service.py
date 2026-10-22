"""檢核表：工項 + 依據 + 檢核結果。

結果的三個值怎麼來。下面的數字是本實作在真實標單（2.契約書.xls，1028 個工項）與
真實規範書（13.施工規範.pdf）上的實測值（2026-10-07），不是設計時的預估：
    OK                  248  章節在本案規範書裡，且該章有相關準則
    SPEC_NOT_INCLUDED   188  對得到章節，但本案規範書沒收錄
    NEEDS_CONFIRMATION  592  沒有章節，或章節無相關準則
與設計時的預估 235 / 188 / 605 相比：188 一致，實測 OK 多 13、NEEDS_CONFIRMATION 少 13。
階段 3 spec 第 2 節的驗收基準已經改成這組實測值。
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.ai.base import ExtractionResult, LLMCallRecord, LLMProvider, LLMResult
from app.core.config import settings
from app.core.db import get_session_factory
from app.core.enums import AIPurpose, CheckResult, DocumentRole, ParseQuality, RegulationType
from app.core.errors import AppError, ProjectNotFoundError, SourceQueryError
from app.models.audit import AIInvocationLog
from app.models.checklist import SpecChapter, WorkItemBasis
from app.models.project import ProjectDocument
from app.repositories.checklist import ChecklistRepository
from app.repositories.documents import DocumentRepository
from app.services.checklist_service import ChecklistService
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
from app.specs import SpecFormatError
from tests.factories import BOQ_HEADER, BOQ_ROWS, make_boq_bytes, make_spec_pdf_bytes

#: 01725 在 PCCES 目錄裡（標單 壹.一.1.1.1 的計價代碼 0172500004 對得到）
SPEC_WITH_BASIS = [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審")]
SPEC_WITHOUT_BASIS = [("01725", "01725", "施工測量", "3.0", "1. 通則 3. 執行")]
#: 一條法律、一條標準，共兩條依據
SPEC_WITH_TWO_BASES = [
    ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 (2) CNS 2473 鋼材 1.5 送審")
]

#: 本檔測試用的迷你綱要規範目錄（PCCES）。刻意不讀 data/pcces_index.json：那是同步下來的
#: 檔案、被 .gitignore 擋掉，測試不該靠它在不在、裡面有什麼。05503、99999 不在這裡。
PCCES_CHAPTERS = [
    {"code": "01725", "name": "施工測量", "edition": "3.0"},
    {"code": "01523", "name": "施工安全衛生及管理", "edition": "4.0"},
    {"code": "03110", "name": "場鑄結構混凝土用模板", "edition": "6.0"},
]


@pytest.fixture(autouse=True)
def pcces_catalog(tmp_path, monkeypatch):
    path = tmp_path / "pcces_index.json"
    path.write_text(
        json.dumps({"source": "pcces", "count": len(PCCES_CHAPTERS), "chapters": PCCES_CHAPTERS}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "PCCES_INDEX_PATH", path)


async def create_project(db_session, name="秀山分隊興建工程", boq_rows=None):
    project = await ProjectService(db_session).create_project(name)
    boq = await DocumentService(db_session).upload("標單.xlsx", make_boq_bytes(rows=boq_rows))
    await db_session.commit()
    await ProjectService(db_session).attach_document(project.id, boq.id, DocumentRole.BOQ)
    await ProjectService(db_session).build_work_items(project.id)
    return project


@pytest.fixture
async def project_with_boq(db_session):
    return await create_project(db_session)


async def attach_spec(db_session, project, chapters):
    spec = await DocumentService(db_session).upload("施工規範.pdf", make_spec_pdf_bytes(chapters))
    await db_session.commit()
    await ProjectService(db_session).attach_document(project.id, spec.id, DocumentRole.SPECIFICATION)
    await db_session.commit()
    return spec


async def degrade(db_session, spec):
    """把規範書標成解析品質不佳（正常是分析流程在量完圖頁佔比後寫的）。"""
    document = await DocumentRepository(db_session).get(
        spec.id, uuid.UUID(settings.DEFAULT_TENANT_ID)
    )
    document.parse_quality = ParseQuality.DEGRADED
    document.parse_quality_note = "105 頁裡有 57 頁以圖為主，圖內的文字未被讀取"
    await db_session.commit()


def row_of(rows, item_no):
    return next(r for r in rows if r.work_item.item_no == item_no)


async def read_back(project_id):
    """用全新的 session 讀檢核表。

    同一個 session 的 identity map 會把 build 剛建的物件原樣還給你——那樣比對的是
    記憶體裡的東西，看不出到底有沒有存進資料庫。
    """
    async with get_session_factory()() as session:
        return await ChecklistService(session).checklist(project_id)


async def count_bases(session) -> int:
    """work_item_bases 表裡總共有幾列。直接數資料庫，不經過檢核表——檢核表只讀得到
    還掛在工項上的依據，沒刪乾淨的舊列也算進來才看得出重複。"""
    return (await session.execute(select(func.count()).select_from(WorkItemBasis))).scalar_one()


def describe(checklist):
    """把檢核表攤成可以直接比較的純資料。"""
    return [
        (
            r.work_item.item_no,
            r.result,
            r.chapter_code,
            None
            if r.chapter is None
            else (
                r.chapter.code,
                r.chapter.title,
                r.chapter.version,
                r.chapter.first_page,
                r.chapter.last_page,
            ),
            sorted((b.basis_type, b.reference, b.detail) for b in r.bases),
        )
        for r in checklist.rows
    ]


class TestBuild:
    async def test_a_work_item_with_basis_is_ok(self, db_session, project_with_boq):
        await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert row.result == CheckResult.OK
        assert any("測量法" in b.reference for b in row.bases)

    async def test_a_row_names_the_spec_chapter_it_came_from(self, db_session, project_with_boq):
        """章名、版本、頁範圍都要從規範書原樣帶過來。用兩頁的章節，first_page 與
        last_page 才分得開——單頁章節兩者相等，寫反了也看不出來。"""
        await attach_spec(
            db_session,
            project_with_boq,
            [
                ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審"),
                ("01725", "01725", "施工測量", "3.0", "2. 產品 （續）"),
                ("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審"),
            ],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        chapter = row_of(rows, "壹.一.1.1.1").chapter

        assert chapter is not None
        assert (chapter.code, chapter.title, chapter.version) == ("01725", "施工測量", "3.0")
        assert (chapter.first_page, chapter.last_page) == (1, 2)

    async def test_a_chapter_missing_from_the_spec_is_flagged(self, db_session, project_with_boq):
        """規範書只有 01523，但標單 壹.一.1.1.1 要的是 01725。"""
        await attach_spec(
            db_session, project_with_boq,
            [("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert row.result == CheckResult.SPEC_NOT_INCLUDED
        # 本案規範書沒有這一章：不能掛一個別章的章節或依據上去
        assert row.chapter is None
        assert row.bases == []

    async def test_a_row_carries_its_chapter_code_even_when_the_spec_lacks_the_chapter(
        self, db_session, project_with_boq
    ):
        """`chapter` 是本案規範書裡對得到的那一章；`chapter_code` 是計價代碼前 5 碼，只看
        工項自己。規範書只有 01523 時，壹.一.1.1.1（01725）與 壹.一.1.2.1（03110）都是
        SPEC_NOT_INCLUDED、chapter 是 None，缺的是哪一章只能從 chapter_code 看出來。
        沒有計價代碼的列沒有章碼。POST 與 GET 讀到的要一樣。"""
        await attach_spec(
            db_session, project_with_boq,
            [("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")],
        )
        built = await ChecklistService(db_session).build(project_with_boq.id)

        for checklist in (built, await read_back(project_with_boq.id)):
            assert {
                r.work_item.item_no: (r.result, r.chapter, r.chapter_code) for r in checklist.rows
            } == {
                "壹.一.1.1.1": (CheckResult.SPEC_NOT_INCLUDED, None, "01725"),
                "壹.一.1.2.1": (CheckResult.SPEC_NOT_INCLUDED, None, "03110"),
                "壹.一.1.3.1": (CheckResult.NEEDS_CONFIRMATION, None, None),
            }

    async def test_a_chapter_without_basis_needs_confirmation(self, db_session, project_with_boq):
        await attach_spec(db_session, project_with_boq, SPEC_WITHOUT_BASIS)

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert row.result == CheckResult.NEEDS_CONFIRMATION
        # 章節找得到，只是沒有宣告相關準則——和「找不到章節」是不同的原因
        assert row.chapter is not None and row.chapter.code == "01725"
        assert row.bases == []

    async def test_a_work_item_without_a_cost_code_needs_confirmation(
        self, db_session, project_with_boq
    ):
        await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.3.1")

        assert row.result == CheckResult.NEEDS_CONFIRMATION
        assert row.chapter is None
        assert row.bases == []

    async def test_a_project_without_a_spec_still_produces_a_checklist(
        self, db_session, project_with_boq
    ):
        """刻意和階段 1 不對稱：沒掛標單是 400（表會是空的），
        沒掛規範書照樣產出（工項都在，只是依據欄空白）。報錯會讓人什麼都拿不到。"""
        result = await ChecklistService(db_session).build(project_with_boq.id)

        assert len(result.rows) > 0
        assert all(r.result == CheckResult.NEEDS_CONFIRMATION for r in result.rows)
        assert all(r.chapter is None and r.bases == [] for r in result.rows)
        assert result.spec_warning is None

    async def test_rebuilding_replaces_instead_of_duplicating(self, db_session):
        """重跑之後要回頭向資料庫查，不能只比對 build() 回傳的清單——兩次都是新建的，
        就算舊的沒有先刪掉，回傳的筆數也會一樣。

        四個工項都有依據，連最後一個也是：只有第一個工項有依據的話，刪除時漏掉最後
        （或第一個）工項的 id 不會被發現。日後把 IN 改成分批刪除，最容易出的就是這種
        邊界錯。總列數要直接數資料庫，漏刪的舊列才會冒出來。"""
        project = await create_project(
            db_session,
            boq_rows=[
                BOQ_HEADER,
                ["壹.一.1.1.1", "施工測量，基地測量", "式", 1, 1, 1, "0172500004"],
                ["壹.一.1.1.2", "施工測量，放樣", "式", 1, 1, 1, "0172500005"],
                ["壹.一.1.1.3", "施工測量，高程測量", "式", 1, 1, 1, "0172500006"],
                ["壹.一.1.1.4", "施工測量，竣工測量", "式", 1, 1, 1, "0172500007"],
            ],
        )
        spec = await attach_spec(db_session, project, SPEC_WITH_TWO_BASES)
        service = ChecklistService(db_session)

        await service.build(project.id)
        assert await count_bases(db_session) == 8  # 4 個工項 × 2 條依據

        await service.build(project.id)

        assert await count_bases(db_session) == 8
        stored = await read_back(project.id)
        assert [sorted(b.reference for b in r.bases) for r in stored.rows] == [["CNS 2473", "測量法"]] * 4
        assert len(await ChecklistRepository(db_session).chapters_by_document(spec.id)) == 1

    async def test_extraction_runs_once_per_chapter(self, db_session, monkeypatch):
        """同一章會對到很多工項（實測 251 個工項對到規範書的 31 章，最多的 16401 一章
        就有 97 個），抽取結果要快取：同一段文字抽 N 次不會讓結果不同，只會慢，而且
        LLM 開著時每次都要錢。快取的結果也必須掛到每一個工項上，不能只給第一個。"""
        project = await create_project(
            db_session,
            boq_rows=[
                BOQ_HEADER,
                ["壹.一.1.1.1", "施工測量，基地測量", "式", 1, 1, 1, "0172500004"],
                ["壹.一.1.1.2", "施工測量，放樣", "式", 1, 1, 1, "0172500005"],
                ["壹.一.1.1.3", "施工測量，竣工測量", "式", 1, 1, 1, "0172500006"],
            ],
        )
        await attach_spec(db_session, project, SPEC_WITH_BASIS)
        service = ChecklistService(db_session)
        extracted: list[str] = []
        real_extract = service.extractor.extract

        async def counting_extract(text):
            extracted.append(text)
            return await real_extract(text)

        monkeypatch.setattr(service.extractor, "extract", counting_extract)

        rows = (await service.build(project.id)).rows

        assert len(extracted) == 1
        assert len(rows) == 3
        assert all(r.result == CheckResult.OK for r in rows)
        assert all([b.reference for b in r.bases] == ["測量法"] for r in rows)

    async def test_each_chapter_gives_its_work_items_its_own_bases(self, db_session):
        """兩章都有相關準則時，各工項拿到的必須是自己那一章的。

        快取的鍵是章碼。上面那個測試只有一章，鍵寫錯了也不影響結果：寫死一個常數、只取
        前兩碼（01725 與 01523 的前兩碼都是 01），或永遠用第一章的文字，每個工項拿到的
        依據都一樣是對的。這裡兩章都有依據，而且工項交錯排列，不是同一章連著出現。"""
        project = await create_project(
            db_session,
            boq_rows=[
                BOQ_HEADER,
                ["壹.一.1.1.1", "施工測量，基地測量", "式", 1, 1, 1, "0172500004"],
                ["壹.一.1.2.1", "施工安全衛生，安全衛生管理", "式", 1, 1, 1, "0152300001"],
                ["壹.一.1.1.2", "施工測量，放樣", "式", 1, 1, 1, "0172500005"],
                ["壹.一.1.2.2", "施工安全衛生，安全衛生教育訓練", "式", 1, 1, 1, "0152300002"],
            ],
        )
        await attach_spec(
            db_session, project,
            [
                ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審"),
                ("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審"),
            ],
        )

        rows = (await ChecklistService(db_session).build(project.id)).rows

        assert {r.work_item.item_no: [b.reference for b in r.bases] for r in rows} == {
            "壹.一.1.1.1": ["測量法"],
            "壹.一.1.2.1": ["職業安全衛生法"],
            "壹.一.1.1.2": ["測量法"],
            "壹.一.1.2.2": ["職業安全衛生法"],
        }


class TestSpecNotIncluded:
    """「本案規範未收錄」要同時滿足兩件事：本案規範書沒有這一章，而且綱要規範（PCCES）
    有這一章。少了後面那件，標單裡任何一個對不上的章碼都會被說成「規範書漏收」。"""

    async def test_a_code_that_is_no_pcces_chapter_is_not_called_missing(self, db_session):
        """章碼不是綱要規範的任何一章（各機關自訂、或舊版編號；真實標單有 74 個工項是
        這樣，例如 16050），沒有任何依據說規範書「應該有」它——只能請人確認，
        不能說本案規範未收錄。對照列 01725 是 PCCES 有、規範書沒有，那才是漏收。"""
        project = await create_project(
            db_session,
            boq_rows=[
                BOQ_HEADER,
                ["壹.一.1.1.1", "自訂工項", "式", 1, 1, 1, "9999900001"],
                ["壹.一.1.1.2", "施工測量", "式", 1, 1, 1, "0172500004"],
            ],
        )
        await attach_spec(
            db_session, project,
            [("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project.id)).rows

        assert row_of(rows, "壹.一.1.1.1").result == CheckResult.NEEDS_CONFIRMATION
        assert row_of(rows, "壹.一.1.1.2").result == CheckResult.SPEC_NOT_INCLUDED

    async def test_a_spec_chapter_unknown_to_pcces_still_matches(self, db_session):
        """本案規範書自己的章不一定在綱要規範裡（真實規範書 86 章有 12 章不在，例如
        05503，組碼 05500 與章碼不同）。所以要先比規範書、再用 PCCES 判斷漏收——
        反過來先問 PCCES 的話，這些章的工項會全部對不上。"""
        project = await create_project(
            db_session,
            boq_rows=[BOQ_HEADER, ["壹.一.1.1.1", "金屬結構", "式", 1, 1, 1, "0550300001"]],
        )
        await attach_spec(
            db_session, project,
            [("05500", "05503", "金屬結構", "5.0", "1.4 相關準則 (1) 勞動基準法 1.5 資料送審")],
        )

        row = row_of((await ChecklistService(db_session).build(project.id)).rows, "壹.一.1.1.1")

        assert row.result == CheckResult.OK
        assert row.chapter is not None and row.chapter.code == "05503"
        assert [b.reference for b in row.bases] == ["勞動基準法"]


class TestSpecWarning:
    async def test_a_degraded_spec_document_warns_in_the_checklist(
        self, db_session, project_with_boq
    ):
        """規範書若大量是圖，章節內容可能殘缺，依據就不完整。
        不講的話使用者會以為依據是齊的——這是 parse_quality 守門第一次被用到。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await degrade(db_session, spec)

        result = await ChecklistService(db_session).build(project_with_boq.id)

        assert result.spec_warning is not None
        assert "以圖為主" in result.spec_warning

    async def test_a_clean_spec_document_has_no_warning(self, db_session, project_with_boq):
        await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)

        result = await ChecklistService(db_session).build(project_with_boq.id)

        assert result.spec_warning is None

    async def test_reading_back_keeps_the_warning(self, db_session, project_with_boq):
        """使用者多半是用 GET 看檢核表，不是每次都重建；警告只在 POST 的回應裡
        就等於大部分時候看不到。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await ChecklistService(db_session).build(project_with_boq.id)
        await degrade(db_session, spec)

        result = await read_back(project_with_boq.id)

        assert result.spec_warning is not None
        assert "以圖為主" in result.spec_warning


class TestReadBack:
    async def test_get_does_not_rebuild(self, db_session, project_with_boq):
        """GET 只讀已經建好的依據。重建是 POST 的事——1028 個工項重跑一次不便宜，
        而且 GET 有副作用會讓人很難推理。"""
        await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        service = ChecklistService(db_session)
        await service.build(project_with_boq.id)

        result = await service.checklist(project_with_boq.id)
        row = row_of(result.rows, "壹.一.1.1.1")

        assert row.result == CheckResult.OK
        assert any("測量法" in b.reference for b in row.bases)

    async def test_get_returns_what_the_build_returned(self, db_session, project_with_boq):
        """三種結果各一筆，逐列、逐欄比對——用全新的 session 讀，才證明 POST 回傳的
        東西真的存下來了，而且 GET 讀回來的和 POST 看到的是同一張表。"""
        await attach_spec(
            db_session,
            project_with_boq,
            [
                ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 (2) CNS 2473 鋼材 1.5 送審"),
                ("01725", "01725", "施工測量", "3.0", "2. 產品 （續）"),
                ("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審"),
            ],
        )
        built = await ChecklistService(db_session).build(project_with_boq.id)

        stored = await read_back(project_with_boq.id)

        assert {r.result for r in built.rows} == set(CheckResult)
        assert describe(stored) == describe(built)

    async def test_get_before_any_build_builds_nothing(self, db_session, project_with_boq):
        """GET 不能順手建：從沒建過的專案讀，依據與章節索引都還是空的，
        而且讀完之後資料庫裡也沒有多出東西。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)

        result = await ChecklistService(db_session).checklist(project_with_boq.id)

        assert all(r.bases == [] and r.chapter is None for r in result.rows)
        assert await ChecklistRepository(db_session).chapters_by_document(spec.id) == []
        assert await ChecklistRepository(db_session).bases_by_project(project_with_boq.id) == {}

    async def test_get_without_a_spec_still_produces_a_checklist(
        self, db_session, project_with_boq
    ):
        """使用者最先碰到的狀態：建了專案、建了工項，還沒上傳規範書就先看檢核表。
        GET 也要給一張表（工項都在、依據欄空白、沒有警告），不能報錯。POST 同一件事的
        對照在 test_a_project_without_a_spec_still_produces_a_checklist。

        標單裡 壹.一.1.1.1（01725）和 壹.一.1.2.1（03110）都是 PCCES 目錄有的章，所以這個
        測試也守住：沒有規範書時，GET 不能把「什麼都沒索引」當成「索引裡沒有這一章」，
        說出「本案規範未收錄」——那是把「你還沒上傳規範書」指成「規範書漏收這一章」。"""
        result = await ChecklistService(db_session).checklist(project_with_boq.id)

        assert {r.work_item.item_no for r in result.rows} == {
            "壹.一.1.1.1", "壹.一.1.2.1", "壹.一.1.3.1",
        }
        assert all(r.result == CheckResult.NEEDS_CONFIRMATION for r in result.rows)
        assert all(r.chapter is None and r.bases == [] for r in result.rows)
        assert result.spec_warning is None

    async def test_get_does_not_reread_the_spec_file(self, db_session, project_with_boq):
        """重讀 772 頁的規範書是重建的事。檔案不在了，GET 照樣要讀得回已經建好的。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await ChecklistService(db_session).build(project_with_boq.id)
        Path(spec.storage_path).unlink()

        result = await read_back(project_with_boq.id)

        assert row_of(result.rows, "壹.一.1.1.1").result == CheckResult.OK


class TestBasisType:
    async def test_a_standard_is_quoted_not_verified(self, db_session, project_with_boq):
        """CNS 沒有資料來源可查證，只引述。走比對管線會標成「查無此法規」，
        那會讓人以為規範引用了不存在的標準。"""
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) CNS 2473 鋼材 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert any(b.basis_type == "standard" for b in row.bases)
        assert [b.reference for b in row.bases] == ["CNS 2473"]

    async def test_laws_and_standards_are_told_apart(self, db_session, project_with_boq):
        """同一章裡兩種都有時，各自帶著自己的類型——只要有一邊寫死，上面那個
        「有標準」的測試照樣會過。"""
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 (2) CNS 2473 鋼材 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert {b.reference: b.basis_type for b in row.bases} == {
            "測量法": "law",
            "CNS 2473": "standard",
        }


class TestBasisSource:
    async def test_the_source_names_the_chapter_but_never_invents_a_section(
        self, db_session, project_with_boq
    ):
        """相關準則不一定在 1.4（實測 01523、01574、02786、03110 四章編在 1.3），
        而 basis_block 不回傳小節號。出處只寫到章：寫一個看起來精確、其實是編造的
        小節號，是這個專案一路在防的錯。這一章的相關準則在 1.3，出處就不能說 1.4。"""
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.3 相關準則 (1) 測量法 1.4 資料送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        row = row_of(rows, "壹.一.1.1.1")

        assert row.result == CheckResult.OK
        assert {b.detail for b in row.bases} == {"第01725章 相關準則"}


class RecordingLLM(LLMProvider):
    """測試用的假 LLM：什麼也抽不到，但每次被呼叫都會附上稽核紀錄、並記下輸入。"""

    name = "recording"

    def __init__(self):
        self.inputs: list[str] = []

    @property
    def model(self) -> str:
        return "recording-model"

    async def extract_regulations(self, text):
        self.inputs.append(text)
        record = LLMCallRecord(
            purpose=AIPurpose.EXTRACTION,
            model=self.model,
            prompt_version="test",
            input_text=text,
            output_json={"items": []},
        )
        return LLMResult(value=ExtractionResult(items=[]), record=record)

    async def judge_similarity(self, name_a, name_b, context=""):
        return LLMResult(value=None)

    async def summarize_for_report(self, findings):
        return LLMResult(value=None)


class TestLlmAudit:
    async def test_an_llm_call_leaves_an_audit_record(
        self, db_session, project_with_boq, monkeypatch
    ):
        """規則與字典都抽不到時，抽取管線會改問 LLM。每一次 LLM 呼叫都要寫進
        ai_invocation_log（docs/architecture.md 第 5 節）——管線只負責把紀錄交回來，
        寫不寫是呼叫端的事。"""
        llm = RecordingLLM()
        monkeypatch.setattr("app.services.checklist_service.get_llm_provider", lambda: llm)
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 依現場狀況辦理之各項作業 1.5 資料送審")],
        )

        await ChecklistService(db_session).build(project_with_boq.id)

        logs = (await db_session.execute(select(AIInvocationLog))).scalars().all()
        assert llm.inputs == ["(1) 依現場狀況辦理之各項作業"]
        assert [(log.purpose, log.model, log.input_text) for log in logs] == [
            (AIPurpose.EXTRACTION, "recording-model", "(1) 依現場狀況辦理之各項作業")
        ]


class TestGuards:
    @pytest.mark.parametrize("entry", ["build", "checklist"])
    async def test_unknown_project_raises(self, db_session, entry):
        """對不存在的專案要回 404（ProjectNotFoundError），不是一張空的檢核表。"""
        with pytest.raises(ProjectNotFoundError):
            await getattr(ChecklistService(db_session), entry)(uuid.uuid4())

    async def test_a_spec_that_cannot_be_read_leaves_the_previous_build_intact(
        self, db_session, project_with_boq
    ):
        """重跑失敗不能把上一次建好的清掉：先讀規範書、讀得懂才動資料庫。

        不能只靠 session 關掉時的 rollback——呼叫端接住錯誤、照常 commit 同一個
        session（例如一次處理好幾個專案的批次）時，先動了資料庫，清掉的那一半就存下去了。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        service = ChecklistService(db_session)
        await service.build(project_with_boq.id)
        Path(spec.storage_path).write_bytes(b"this is not a pdf")

        with pytest.raises(SpecFormatError):
            await service.build(project_with_boq.id)
        await db_session.commit()

        row = row_of((await read_back(project_with_boq.id)).rows, "壹.一.1.1.1")
        assert row.result == CheckResult.OK
        assert [b.reference for b in row.bases] == ["測量法"]

    async def test_an_unreadable_catalog_leaves_the_previous_build_intact(
        self, db_session, project_with_boq, tmp_path, monkeypatch
    ):
        """規範書讀得懂、但綱要規範目錄讀不到：一樣要在動資料庫之前就失敗。
        這裡把規範書換成另一份（同一筆文件紀錄、檔案內容換掉）——若先寫了新的章節索引
        才發現目錄壞了，呼叫端照常 commit 之後，索引就是新的、依據卻是舊的。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await ChecklistService(db_session).build(project_with_boq.id)
        Path(spec.storage_path).write_bytes(
            make_spec_pdf_bytes(
                [("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")]
            )
        )
        catalog = settings.PCCES_INDEX_PATH
        monkeypatch.setattr(settings, "PCCES_INDEX_PATH", tmp_path / "no-such-catalog.json")

        with pytest.raises(SourceQueryError):
            await ChecklistService(db_session).build(project_with_boq.id)
        await db_session.commit()

        monkeypatch.setattr(settings, "PCCES_INDEX_PATH", catalog)
        row = row_of((await read_back(project_with_boq.id)).rows, "壹.一.1.1.1")
        assert row.chapter is not None and row.chapter.code == "01725"
        assert [b.reference for b in row.bases] == ["測量法"]

    @pytest.mark.parametrize("entry", ["build", "checklist"])
    async def test_a_spec_link_whose_document_is_gone_is_reported(
        self, db_session, project_with_boq, entry
    ):
        """掛了規範書、但檔案紀錄不見了，和「沒掛規範書」是兩回事：照沒掛處理會產出
        一張全部「請確認依據」的表，看起來像「這個案子沒有依據」。
        SQLite 預設不強制外鍵，刪掉文件後專案的 link 會留著——正是要擋的狀態。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await db_session.delete(
            await DocumentRepository(db_session).get(
                spec.id, uuid.UUID(settings.DEFAULT_TENANT_ID)
            )
        )
        await db_session.commit()

        with pytest.raises(AppError, match="不存在"):
            await getattr(ChecklistService(db_session), entry)(project_with_boq.id)


class TestChapterIndex:
    async def test_chapters_come_back_in_the_order_of_the_spec(
        self, db_session, project_with_boq
    ):
        """依頁碼排，不靠資料庫碰巧怎麼排。章碼重複時 build 與 GET 都取「先出現的」，
        兩條路徑才會挑到同一章——前提就是這個順序是確定的。"""
        spec = await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        repo = ChecklistRepository(db_session)

        await repo.replace_chapters(
            spec.id,
            [
                SpecChapter(
                    document_id=spec.id, code=code, title="", version="1.0",
                    first_page=page, last_page=page,
                )
                for code, page in (("03110", 30), ("01725", 10), ("01523", 20))
            ],
        )

        found = await repo.chapters_by_document(spec.id)
        assert [(c.first_page, c.code) for c in found] == [(10, "01725"), (20, "01523"), (30, "03110")]


class TestSpecSelection:
    async def test_with_two_specs_attached_the_first_one_is_indexed_every_time(
        self, db_session, project_with_boq
    ):
        """同一個專案掛了兩份施工規範書時，建檢核表對著哪一份建索引要固定：最早掛上去的那份。
        SQL 沒有 ORDER BY 就不保證順序，PostgreSQL 可能這次回甲、下次回乙。

        甲（先掛）只有 01523，乙（後掛）有 01725：用甲建的話 壹.一.1.1.1（01725）是
        SPEC_NOT_INCLUDED，誤用乙就會是 OK。連結的寫入順序與 id 順序刻意和掛上去的先後相反，
        所以拿掉排序、或只照 id 排，都會選到乙。"""
        early = await DocumentService(db_session).upload(
            "規範甲.pdf",
            make_spec_pdf_bytes(
                [("01523", "01523", "施工安全衛生及管理", "4.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")]
            ),
        )
        late = await DocumentService(db_session).upload(
            "規範乙.pdf", make_spec_pdf_bytes(SPEC_WITH_BASIS)
        )
        start = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        # 寫入順序：乙 → 甲；id 順序：乙(1) → 甲(2)；掛上去的先後：甲 → 乙
        for number, document, added_at in (
            (1, late, start + timedelta(hours=1)),
            (2, early, start),
        ):
            db_session.add(
                ProjectDocument(
                    id=uuid.UUID(int=number),
                    project_id=project_with_boq.id,
                    document_id=document.id,
                    role=DocumentRole.SPECIFICATION,
                    added_at=added_at,
                )
            )
        await db_session.commit()

        built = await ChecklistService(db_session).build(project_with_boq.id)

        row = row_of(built.rows, "壹.一.1.1.1")
        assert row.result == CheckResult.SPEC_NOT_INCLUDED
        repo = ChecklistRepository(db_session)
        assert [c.code for c in await repo.chapters_by_document(early.id)] == ["01523"]
        assert await repo.chapters_by_document(late.id) == []


class TestBasisOrder:
    """bases_by_project 的順序要固定：SQL 沒有 ORDER BY 就不保證順序，SQLite 碰巧依寫入
    順序給，PostgreSQL 不一定。所以資料刻意讓「寫入順序」「id 順序」「應有順序」三者互不
    相同——拿掉 ORDER BY、或只照其中一種排，都會被抓到。"""

    @staticmethod
    def basis(item, reference, created_at, number):
        return WorkItemBasis(
            id=uuid.UUID(int=number),
            work_item_id=item.id,
            basis_type="law",
            reference=reference,
            created_at=created_at,
        )

    async def test_bases_come_back_oldest_first(self, db_session, project_with_boq):
        item = (await ProjectService(db_session).work_items(project_with_boq.id))[0]
        start = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        repo = ChecklistRepository(db_session)

        # 應有順序（建立時間）：測量法 → 勞動基準法 → 職業安全衛生法
        # 寫入順序：職安 → 測量 → 勞基；id 順序：勞基(1) → 職安(2) → 測量(3)
        await repo.replace_bases(
            [item.id],
            [
                self.basis(item, "職業安全衛生法", start + timedelta(seconds=3), 2),
                self.basis(item, "測量法", start + timedelta(seconds=1), 3),
                self.basis(item, "勞動基準法", start + timedelta(seconds=2), 1),
            ],
        )

        found = (await repo.bases_by_project(project_with_boq.id))[item.id]
        assert [b.reference for b in found] == ["測量法", "勞動基準法", "職業安全衛生法"]

    async def test_bases_made_at_the_same_instant_still_come_back_in_a_fixed_order(
        self, db_session, project_with_boq
    ):
        """時間戳一樣的幾筆（時鐘解析度不夠時會發生）要有第二層排序，不然它們之間的
        順序每次查詢都可能不同。這裡以 id 為準。"""
        item = (await ProjectService(db_session).work_items(project_with_boq.id))[0]
        instant = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        repo = ChecklistRepository(db_session)

        # 寫入順序：id 3 → 1 → 2
        await repo.replace_bases(
            [item.id],
            [
                self.basis(item, "職業安全衛生法", instant, 3),
                self.basis(item, "測量法", instant, 1),
                self.basis(item, "勞動基準法", instant, 2),
            ],
        )

        found = (await repo.bases_by_project(project_with_boq.id))[item.id]
        assert [b.reference for b in found] == ["測量法", "勞動基準法", "職業安全衛生法"]


class TestIsolation:
    async def test_building_one_project_leaves_the_others_untouched(
        self, db_session, project_with_boq
    ):
        """重建只能清自己專案的依據、自己那份規範書的章節；讀也只能讀自己的。
        兩個專案各有一份規範書，輪流重建，各自的檢核表都要維持自己的。"""
        other = await create_project(
            db_session, "另一個工程", boq_rows=[*BOQ_ROWS, ["壹.一.1.4.1", "雜項", "式", 1, 1, 1, ""]]
        )
        await attach_spec(db_session, project_with_boq, SPEC_WITH_BASIS)
        await attach_spec(
            db_session, other,
            [
                ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 勞動基準法 1.5 資料送審"),
                ("03110", "03110", "模板", "3.0", "1. 通則 3. 執行"),
            ],
        )
        service = ChecklistService(db_session)

        await service.build(project_with_boq.id)
        await service.build(other.id)
        await service.build(project_with_boq.id)

        mine = await read_back(project_with_boq.id)
        theirs = await read_back(other.id)

        # 同一個章碼，各自讀到各自規範書寫的依據
        assert [b.reference for b in row_of(mine.rows, "壹.一.1.1.1").bases] == ["測量法"]
        assert [b.reference for b in row_of(theirs.rows, "壹.一.1.1.1").bases] == ["勞動基準法"]
        # 另一個專案收了 03110，這個專案沒有——不能因為放在同一個資料庫就讀得到
        assert row_of(mine.rows, "壹.一.1.2.1").result == CheckResult.SPEC_NOT_INCLUDED
        assert row_of(theirs.rows, "壹.一.1.2.1").result == CheckResult.NEEDS_CONFIRMATION
        assert row_of(theirs.rows, "壹.一.1.2.1").chapter.code == "03110"


class TestVerification:
    """查證狀態只在查得到完全同名時才有值。"""

    async def test_an_exact_match_gets_its_status(self, db_session, project_with_boq, monkeypatch):
        """規範書宣告「職業安全衛生法」，而索引裡有同名的一部法。"""
        from app.core.enums import RegulationStatus
        from app.services import checklist_service

        async def fake_verify(names, source):
            # 從收到的 names 回答：模擬「索引裡只有這一部法」。沒送這個名稱就得不到狀態，
            # 寫死回傳值的話，就算 build 一個名稱都沒送，這個測試照樣會過。
            return {name: RegulationStatus.ACTIVE for name in names if name == "職業安全衛生法"}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        basis = next(b for r in rows for b in r.bases if b.reference == "職業安全衛生法")

        assert basis.verification_status == RegulationStatus.ACTIVE

    async def test_a_name_not_in_the_index_stays_null(self, db_session, project_with_boq, monkeypatch):
        """未查證是 None，不是 NOT_FOUND——我們沒有立場說那部法規不存在。"""
        from app.services import checklist_service

        async def fake_verify(names, source):
            return {}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 屋內線路裝置規則 1.5 送審")],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        basis = next(b for r in rows for b in r.bases if b.reference == "屋內線路裝置規則")

        assert basis.verification_status is None

    async def test_standards_are_never_sent_for_verification(self, db_session, project_with_boq, monkeypatch):
        """標準沒有資料來源可查，連送都不要送。"""
        from app.services import checklist_service

        sent: list[set[str]] = []

        async def fake_verify(names, source):
            sent.append(set(names))
            return {}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) CNS 2473 (2) 職業安全衛生法 1.5 送審")],
        )

        await ChecklistService(db_session).build(project_with_boq.id)

        # 精確斷言送了什麼，而不只是「沒送標準」：只斷言否定的話，一個名稱都沒送
        # （sent == [set()]）也會過，查證就會悄悄地永遠不執行。依相異名稱查一次，所以
        # 剛好一批、剛好一個名稱。
        assert sent == [{"職業安全衛生法"}]

        # 標準存進資料庫的狀態也要是 None（用全新 session 讀，見 read_back）。「沒送查」
        # 不等於「沒存東西」：存成 NOT_FOUND 就是宣稱我們查過、而且它不存在。
        rows = (await read_back(project_with_boq.id)).rows
        standard = next(b for r in rows for b in r.bases if b.reference == "CNS 2473")
        assert standard.basis_type == RegulationType.STANDARD
        assert standard.verification_status is None

    async def test_the_status_survives_a_read_back(self, db_session, project_with_boq, monkeypatch):
        """GET 只讀，查證狀態要在資料庫裡，不是每次重查。"""
        from app.core.enums import RegulationStatus
        from app.services import checklist_service

        async def fake_verify(names, source):
            return {"職業安全衛生法": RegulationStatus.REPEALED}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)
        await attach_spec(
            db_session, project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審")],
        )
        await ChecklistService(db_session).build(project_with_boq.id)

        # 用全新的 session 讀。同一個 session 讀到的是 identity map 裡 build 剛建的物件，
        # 看的是記憶體而不是資料庫——狀態有沒有真的存進去，要換 session 才看得出來。
        rows = (await read_back(project_with_boq.id)).rows
        basis = next(b for r in rows for b in r.bases if b.reference == "職業安全衛生法")

        assert basis.verification_status == RegulationStatus.REPEALED

    async def test_a_name_on_many_rows_is_verified_once(self, db_session, project_with_boq, monkeypatch):
        """同一部法出現在兩章、兩個工項上：查證依相異名稱，不是依筆數。

        只有一筆依據的測試分不出「每個名稱查一次」和「每筆依據查一次」——這裡讓同一個名稱
        落在兩筆依據上，後者就會送出兩批。
        """
        from app.core.enums import RegulationStatus
        from app.services import checklist_service

        sent: list[set[str]] = []

        async def fake_verify(names, source):
            sent.append(set(names))
            return {name: RegulationStatus.ACTIVE for name in names}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)
        await attach_spec(
            db_session, project_with_boq,
            [
                ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審"),
                ("03110", "03110", "模板", "3.0", "1.4 相關準則 (1) 職業安全衛生法 1.5 送審"),
            ],
        )

        rows = (await ChecklistService(db_session).build(project_with_boq.id)).rows
        bases = [b for r in rows for b in r.bases]

        assert len(bases) == 2
        assert sent == [{"職業安全衛生法"}]
        # 查一次的結果要寫回每一筆同名的依據
        assert [b.verification_status for b in bases] == [RegulationStatus.ACTIVE] * 2
