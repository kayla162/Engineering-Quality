"""總覽（Dashboard）API 契約。"""

import uuid

from pydantic import BaseModel


class DocumentStats(BaseModel):
    total: int
    by_status: dict[str, int]
    #: 解析品質不佳（圖頁或 OCR 頁太多）的文件數
    degraded: int
    failed: int


class ReferenceStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_review: dict[str, int]
    #: 狀態需要人工介入、且還沒覆核過的引用數
    needs_action: int
    #: 比對到的法規來自哪個資料來源（mock 是假資料）
    by_source: dict[str, int]


class TopRegulation(BaseModel):
    regulation_id: uuid.UUID
    name: str
    status: str
    source: str
    references: int
    documents: int


class DocumentNeedingAction(BaseModel):
    document_id: uuid.UUID
    filename: str
    parse_quality: str
    references: int
    unreviewed: int
    needs_action: int


class DashboardOut(BaseModel):
    documents: DocumentStats
    references: ReferenceStats
    projects: int
    #: 法規異動監控偵測到、還沒有人確認的變動數
    open_regulation_changes: int
    top_regulations: list[TopRegulation]
    documents_needing_action: list[DocumentNeedingAction]
