"""Compose existing stored results; never rebuild, infer links, or save decisions."""
import re
import uuid
from collections import Counter

from app.core.enums import CheckResult
from app.core.errors import SourceQueryError
from app.schemas.checklist import ChecklistItemOut
from app.schemas.integrated_checklist import (
    IntegratedChecklistOut, IntegratedDrawingOut, IntegratedItemOut,
    IntegratedMethodOut, IntegratedSummaryOut, MethodCandidateOut,
)
from app.services.checklist_service import ChecklistService
from app.services.drawing_service import DrawingService

# A labelled literal is a candidate only. Shapes, generic nouns and neighbouring
# page text cannot tell us which construction method belongs to this item.
_METHOD = re.compile(r"(?:施工工法|施工方法|工法)\s*[:：]\s*([^\n\r；;。！？!?]{2,100})")
_UNSPECIFIED = re.compile(r"未指定|待定|待確認|另定|另詳|不得|禁止|禁用|不可|不採用|不適用")
_SENTENCE_BOUNDARY = re.compile(r"[\n\r；;。！？!?]")


def method_candidates(text: str, *, source: str,
                      drawing_item_id: uuid.UUID | None = None) -> list[MethodCandidateOut]:
    candidates = []
    for match in _METHOD.finditer(text):
        value = match.group(1).strip()
        # Negation can precede the label ("不得採用之工法：...").
        # Bound it to this sentence so an earlier prohibition does not erase a
        # subsequent, explicitly labelled candidate from a different sentence.
        prefix = _SENTENCE_BOUNDARY.split(text[:match.start()])[-1]
        if _UNSPECIFIED.search(prefix) or _UNSPECIFIED.search(value):
            continue
        candidates.append(MethodCandidateOut(
            text=value, source=source, evidence=text, drawing_item_id=drawing_item_id,
        ))
    return candidates


class _AvailableChecklistService(ChecklistService):
    """Keep local project evidence readable when the optional catalogue is down.

    Reuse ChecklistService's assembly and stored bases. Only the external
    catalogue conclusion degrades to unknown; the old API remains unchanged.
    """
    catalog_warning: str | None = None

    async def _catalogued(self, work_items, spec_codes):
        try:
            return await super()._catalogued(work_items, spec_codes)
        except SourceQueryError:
            self.catalog_warning = (
                "PCCES 目錄目前無法查詢，未收錄章節改列請確認依據；"
                "本案已儲存的規範依據仍保留，未重新查證。")
            return set()


class IntegratedChecklistService:
    def __init__(self, session):
        self.session = session

    async def snapshot(self, project_id: uuid.UUID) -> IntegratedChecklistOut:
        basis_service = _AvailableChecklistService(self.session)
        checklist = await basis_service.checklist(project_id)
        # Materialize before DrawingService expires its ORM identity map.
        bases = {
            str(row.work_item.id): ChecklistItemOut.from_row(row)
            for row in checklist.rows
        }
        snapshot = await DrawingService(self.session).snapshot(project_id)
        sheets = {sheet["id"]: sheet for sheet in snapshot["sheets"]}
        documents = {doc["id"]: doc["filename"] for doc in snapshot["documents"]}
        drawing_items = {item["id"]: item for item in snapshot["items"]}
        warnings = [
            snapshot["disclaimer"],
            "工法僅擷取明確文字作為候選；尚未經人員指定，不能作為施工指示。",
        ]
        if checklist.spec_warning:
            warnings.append(checklist.spec_warning)
        if basis_service.catalog_warning:
            warnings.append(basis_service.catalog_warning)
        if not bases:
            warnings.append("尚無標單工項，僅呈現圖說候選，不能據此判定標單缺項。")
        if not sheets:
            warnings.append("尚無已索引圖頁，不能據此判定圖說缺漏。")
        if snapshot["summary"]["unindexed_documents"]:
            warnings.append("部分契約圖尚未建立索引，圖說來源可能不完整。")
        if snapshot["summary"]["unreadable_pages"]:
            warnings.append("部分圖頁缺少圖號或圖名，請核對原圖。")

        rows = []
        for union in snapshot["union"]:
            work_id = union["work_item_id"]
            basis = bases.get(work_id)
            drawings = []
            candidates = method_candidates(union["name"], source=f"work:{work_id}:name") if work_id else []
            for drawing_id in union["drawing_item_ids"]:
                item = drawing_items[drawing_id]
                sheet = sheets[item["sheet_id"]]
                drawings.append(IntegratedDrawingOut(
                    id=item["id"], sheet_id=sheet["id"], document_id=sheet["document_id"],
                    filename=documents.get(sheet["document_id"]), page=sheet["page"],
                    number=sheet["number"], title=sheet["title"],
                    evidence=item["evidence"], sheet_evidence=sheet["evidence"],
                    review_status=item["review_status"], review_note=item["review_note"],
                    warning=sheet["warning"],
                ))
                # Only this item's explicit text and its associated drawing title;
                # do not mine whole page evidence for unrelated methods.
                for field, value in (("name", item["name"]), ("evidence", item["evidence"]),
                                     ("title", sheet["title"] or "")):
                    candidates.extend(method_candidates(
                        value, source=f"drawing:{drawing_id}:{field}",
                        drawing_item_id=uuid.UUID(drawing_id)))
            rows.append(IntegratedItemOut(
                key=f"work:{work_id}" if work_id else f"drawing:{union['drawing_item_ids'][0]}",
                work_item_id=work_id, item_no=union["item_no"], name=union["name"],
                source_status=union["status"],
                basis_result=basis.result if basis else None,
                chapter_code=basis.chapter_code if basis else None,
                chapter=basis.chapter if basis else None, bases=basis.bases if basis else [],
                drawings=drawings,
                method=IntegratedMethodOut(
                    status="pending" if candidates else "unspecified", candidates=candidates),
            ))
        source_counts = Counter(row.source_status for row in rows)
        basis_counts = Counter(row.basis_result for row in rows)
        rejected = sum(item["review_status"] == "rejected" for item in snapshot["items"])
        stale = sum(item["review_status"] == "stale" for item in snapshot["items"])
        if rejected:
            warnings.append(f"{rejected} 筆圖項已由人員排除，不列入聯集；原紀錄與備註仍保留。")
        if stale:
            warnings.append(f"{stale} 筆圖項的人工確認已過期，須重新核對目前標單。")
        return IntegratedChecklistOut(
            project_id=project_id, revision=snapshot["revision"], total=len(rows),
            summary=IntegratedSummaryOut(
                total=len(rows), work_items=len(bases), matched=source_counts["both"],
                needs_confirmation=source_counts["needs_confirmation"],
                drawing_candidates=source_counts["drawing_candidate"],
                drawing_only=source_counts["drawing_only"], rejected_items=rejected,
                pending_items=snapshot["summary"]["pending_items"],
                basis_ok=basis_counts[CheckResult.OK],
                basis_spec_not_included=basis_counts[CheckResult.SPEC_NOT_INCLUDED],
                basis_needs_confirmation=basis_counts[CheckResult.NEEDS_CONFIRMATION],
            ),
            warnings=warnings, items=rows,
        )
