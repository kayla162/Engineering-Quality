"""系統中所有列舉值的唯一定義處（對應 docs/database.md 第 3 節）。

資料庫欄位一律存字串，不用 PostgreSQL 原生 enum，
這樣新增列舉值時不需要 migration。
"""

from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobStep(StrEnum):
    PARSING = "PARSING"
    EXTRACTING = "EXTRACTING"
    NORMALIZING = "NORMALIZING"
    MATCHING = "MATCHING"
    QUERYING = "QUERYING"
    REPORTING = "REPORTING"


class RegulationStatus(StrEnum):
    """法規狀態。刻意不是「有效/無效」二元判斷，理由見 docs/database.md 第 4 節。"""

    ACTIVE = "ACTIVE"                  # 現行有效
    AMENDED = "AMENDED"                # 已修正（仍有效，但版本已變動）
    REPEALED = "REPEALED"              # 已廢止
    NOT_FOUND = "NOT_FOUND"            # 查無此法規/標準
    POSSIBLE_MATCH = "POSSIBLE_MATCH"  # 找到疑似對應但無法確認，需人工確認
    UNKNOWN = "UNKNOWN"                # 查詢失敗或尚未查詢


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RegulationType(StrEnum):
    LAW = "law"                          # 法律
    REGULATION = "regulation"            # 法規命令、辦法、細則
    STANDARD = "standard"                # CNS / ISO / ASTM / JIS 等標準
    ENGINEERING_SPEC = "engineering_spec"  # 施工規範、設計規範
    CONTRACT_SPEC = "contract_spec"      # 契約條款
    ANNOUNCEMENT = "announcement"        # 公告、函釋、作業要點
    OTHER = "other"


class ExtractionMethod(StrEnum):
    REGEX = "regex"
    DICTIONARY = "dictionary"
    NER = "ner"
    LLM_FALLBACK = "llm_fallback"


class ContentType(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE = "table"
    CELL = "cell"


class AIPurpose(StrEnum):
    EXTRACTION = "extraction"
    SIMILARITY_JUDGEMENT = "similarity_judgement"
    REPORT_SUMMARY = "report_summary"


class DocumentRole(StrEnum):
    """文件在專案裡的角色。

    對應 docs/superpowers/specs/2026-09-11-工項檢核表-design.md 的綠框：
    契約及契約圖、法規、施工規範。法規不是上傳的文件（由 taiwan_law / pcces 提供），
    標單則是工項清單的來源。

    角色決定跑什麼管線：標單走工項抽取，契約與規範走法規抽取。
    把法規抽取跑在標單上只會得到滿頁 NOT_FOUND（實測 38 筆）。
    """

    BOQ = "boq"                      # 標單（詳細價目表）
    CONTRACT = "contract"            # 契約書
    DRAWING = "drawing"              # 契約圖
    SPECIFICATION = "specification"  # 施工規範（常是契約附件）
    OTHER = "other"


class SourceAvailability(StrEnum):
    """已啟用的法規來源整體上能不能查（對應 GET /api/sources）。

    來源需要先跑同步腳本才會就緒，沒就緒時每一筆引用都會是 UNKNOWN。
    分成三級是為了讓前端知道要提示得多大聲。
    """

    OK = "ok"                    # 全部就緒
    DEGRADED = "degraded"        # 部分未就緒：查得到，但涵蓋範圍比預期小
    UNAVAILABLE = "unavailable"  # 全部未就緒（含一個來源都沒啟用）：所有引用都會是 UNKNOWN


#: 需要人工介入的狀態，報告與前端會特別標示
NEEDS_ATTENTION_STATUSES = frozenset(
    {
        RegulationStatus.AMENDED,
        RegulationStatus.REPEALED,
        RegulationStatus.NOT_FOUND,
        RegulationStatus.POSSIBLE_MATCH,
        RegulationStatus.UNKNOWN,
    }
)
