"""EnterpriseRegulationSource：企業內部文件（品質手冊、程序書、作業標準…）。

資料是各租戶自己匯入的文件管制一覽表（見 services/enterprise_document_service.py），
存在資料庫、依租戶隔離。所以這個來源和其他來源不同：`get_sources()` 回傳的共用實例
不知道是哪個租戶，查詢前要先 `for_tenant()` 綁定，拿到只看得見該租戶清單的副本。

比對規則比 mock 嚴格：完全同名、同編號、同別名才給 1.0；其餘用名稱相似度，
低於 MIN_RELEVANCE 不回傳。內部文件常常只差一兩個字（「模板組立作業標準」vs
「模板組立及拆除作業標準」），太寬會把作廢的舊文件對到現行的新文件。

公司是自己文件的發行者，查得到就能確認是不是現行版本（can_confirm_currency=True）。
"""

import uuid

from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RegulationType
from app.core.errors import SourceQueryError
from app.matching.normalizer import clean_text
from app.sources.base import (
    RegulationDetail,
    RegulationSearchResult,
    RegulationSource,
    RegulationVersionInfo,
    SourceReadiness,
)

MIN_RELEVANCE = 0.80
MAX_RESULTS = 5
REMEDY = (
    "租戶管理員在「總覽」的「企業內部文件」匯入 Excel 清單，或執行 "
    "python scripts/import_enterprise_documents.py <清單.xlsx> --tenant <租戶名稱>"
)


def _key(text: str) -> str:
    return clean_text(text).casefold()


class EnterpriseRegulationSource(RegulationSource):
    source_name = "enterprise"

    def __init__(self, documents: list | None = None):
        #: None = 尚未綁定租戶（共用實例）；[] = 已綁定但清單是空的
        self._documents = documents

    async def for_tenant(self, session: AsyncSession, tenant_id: uuid.UUID) -> "EnterpriseRegulationSource":
        from app.services.enterprise_document_service import EnterpriseDocumentService

        return EnterpriseRegulationSource(
            await EnterpriseDocumentService(session, tenant_id).list_documents()
        )

    def readiness(self) -> SourceReadiness:
        if self._documents is None:
            return SourceReadiness(
                source=self.source_name,
                ready=False,
                detail="企業內部文件依租戶分開，登入後才看得到這個租戶有沒有匯入清單",
                remedy=REMEDY,
            )
        if not self._documents:
            return SourceReadiness(
                source=self.source_name,
                ready=False,
                detail="這個租戶還沒有匯入企業內部文件清單，內部文件的引用都會是「查無此法規」",
                remedy=REMEDY,
            )
        return SourceReadiness(source=self.source_name, ready=True)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        documents = self._bound()
        target = _key(query)
        scored = []
        for document in documents:
            keys = {_key(document.name), _key(document.doc_number), *map(_key, document.aliases)}
            if target in keys:
                score = 1.0
            else:
                score = fuzz.ratio(target, _key(document.name)) / 100
            if score >= MIN_RELEVANCE:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].doc_number))
        return [self._to_result(document, score) for score, document in scored[:MAX_RESULTS]]

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        document = self._find(regulation_id)
        if document is None:
            return None
        return RegulationDetail(
            **self._to_result(document, 1.0).model_dump(),
            versions=self._versions(document),
        )

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        document = self._find(regulation_id)
        return self._versions(document) if document else []

    # --- 內部 ---

    def _bound(self) -> list:
        if self._documents is None:
            raise SourceQueryError(self.source_name, "企業內部文件來源尚未綁定租戶，無法查詢")
        return self._documents

    def _find(self, doc_number: str):
        return next((d for d in self._bound() if d.doc_number == doc_number), None)

    def _to_result(self, document, relevance: float) -> RegulationSearchResult:
        note = f"{document.doc_type}，{document.revision}"
        if document.replaced_by:
            note += f"；已由 {document.replaced_by} 取代"
        return RegulationSearchResult(
            external_id=document.doc_number,
            name=document.name,
            type=RegulationType.INTERNAL,
            status=document.status,
            source=self.source_name,
            authority=document.owner,
            effective_date=document.effective_date,
            last_amended_date=document.last_revised_date,
            official_url=None,
            standard_number=document.doc_number,
            note=note,
            relevance=round(relevance, 4),
            can_confirm_currency=True,
        )

    @staticmethod
    def _versions(document) -> list[RegulationVersionInfo]:
        return [
            RegulationVersionInfo(
                version=document.revision,
                effective_date=document.effective_date,
                amended_date=document.last_revised_date,
            )
        ]
