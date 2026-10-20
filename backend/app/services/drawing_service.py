"""圖說索引與人工確認的工項聯集，獨立於施工規範檢核。"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool

from app.core.enums import DocumentRole
from app.core.errors import AppError
from app.drawings.reader import compact, item_names, read_drawings
from app.models.drawing import DrawingItem, DrawingSheet
from app.models.project import Project
from app.repositories.documents import DocumentRepository
from app.repositories.projects import ProjectRepository


def fingerprint(items):
    value = [(str(i.id), i.item_no, i.name, i.cost_code) for i in items]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


class DrawingService:
    def __init__(self, session):
        self.session = session
        self.projects = ProjectRepository(session)
        self.documents = DocumentRepository(session)

    async def require_project(self, project_id):
        if await self.projects.get(project_id) is None:
            raise AppError("找不到指定的專案")

    async def document(self, project_id, document_id):
        await self.require_project(project_id)
        link = await self.projects.get_link(project_id, document_id)
        if not link or link.role != DocumentRole.DRAWING:
            raise AppError("請先將這份文件掛到本專案的契約圖角色")
        doc = await self.documents.get(document_id)
        if doc is None or doc.file_type != "pdf":
            raise AppError("圖說索引目前只接受 PDF")
        return doc

    async def index(self, project_id, request):
        doc = await self.document(project_id, request.document_id)
        path = Path(doc.storage_path)
        def parse():
            from app.drawings.ocr import LocalOCR
            return read_drawings(path, ocr=LocalOCR() if request.use_ocr else None)
        # Complete expensive parsing before modifying the previous index.
        rows = await run_in_threadpool(parse)
        await self.projects.advance_drawing_revision(project_id, request.expected_revision)
        old = select(DrawingSheet.id).where(
            DrawingSheet.project_id == project_id, DrawingSheet.document_id == doc.id)
        await self.session.execute(delete(DrawingItem).where(DrawingItem.sheet_id.in_(old)))
        await self.session.execute(delete(DrawingSheet).where(
            DrawingSheet.project_id == project_id, DrawingSheet.document_id == doc.id))
        seen = {}
        for row in rows:
            if row.number:
                seen[row.number] = seen.get(row.number, 0) + 1
        for row in rows:
            warning = row.warning
            if row.number and seen[row.number] > 1:
                warning = (warning + "；" if warning else "") + "圖號重複，請確認版本／分頁"
            sheet = DrawingSheet(project_id=project_id, document_id=doc.id, page=row.page,
                                 number=row.number, title=row.title, method=row.method,
                                 evidence=row.evidence, warning=warning)
            self.session.add(sheet)
            await self.session.flush()
            for name in item_names(row.title):
                self.session.add(DrawingItem(sheet_id=sheet.id, name=name,
                    evidence=f"由圖名「{row.title}」提出的候選；需核對原圖"))
        await self.session.commit()
        return await self.snapshot(project_id)

    async def sheet(self, project_id, sheet_id):
        sheet = await self.session.get(DrawingSheet, sheet_id)
        if sheet is None or sheet.project_id != project_id:
            raise AppError("圖頁不屬於本專案")
        return sheet

    async def add_item(self, project_id, request):
        await self.projects.advance_drawing_revision(project_id, request.expected_revision)
        await self.sheet(project_id, request.sheet_id)
        self.session.add(DrawingItem(sheet_id=request.sheet_id, name=request.name,
                                     evidence=request.evidence))
        await self.session.commit()
        return await self.snapshot(project_id)

    async def edit_sheet(self, project_id, sheet_id, request):
        await self.projects.advance_drawing_revision(project_id, request.expected_revision)
        sheet = await self.sheet(project_id, sheet_id)
        # Preserve original evidence and warning; a title edit is not complete page review.
        sheet.number, sheet.title = request.number, request.title
        sheet.method = request.source
        if request.source == "assisted":
            notice = "AI 圖框轉錄，仍待人工核對；非工程覆核結論"
            if notice not in (sheet.warning or ""):
                sheet.warning = (sheet.warning + "；" if sheet.warning else "") + notice
        items = (await self.session.scalars(
            select(DrawingItem).where(DrawingItem.sheet_id == sheet_id))).all()
        for item in items:
            item.review_status = "pending"
            item.work_item_ids = []
            item.review_fingerprint = None
        await self.session.commit()
        return await self.snapshot(project_id)

    async def review(self, project_id, item_id, request):
        await self.projects.advance_drawing_revision(project_id, request.expected_revision)
        item = await self.session.get(DrawingItem, item_id)
        if item is None:
            raise AppError("找不到圖項")
        await self.sheet(project_id, item.sheet_id)
        work = await self.projects.work_items(project_id)
        allowed = {i.id for i in work}
        if request.decision == "confirmed" and not work:
            raise AppError("尚無標單工項，不能確認配對或斷定圖說獨有")
        if not set(request.work_item_ids) <= allowed:
            raise AppError("選取的標單工項不屬於本專案或已重建")
        if request.decision != "confirmed" and request.work_item_ids:
            raise AppError("只有確認的圖項可以建立工項關聯")
        item.review_status = request.decision
        item.work_item_ids = sorted({str(i) for i in request.work_item_ids})
        item.review_fingerprint = fingerprint(work)
        item.review_note = request.note
        await self.session.commit()
        return await self.snapshot(project_id)

    async def snapshot(self, project_id):
        # Mutations reuse this session after commit. Discard retained ORM values
        # so another writer's revision cannot accompany our pre-commit objects.
        self.session.expire_all()
        await self.require_project(project_id)
        # Read the token before any content. Concurrent updates may make the view
        # stale, but cannot give earlier content a newer, valid write token.
        revision = await self.session.scalar(select(Project.drawing_revision).where(Project.id == project_id))
        sheets = list((await self.session.scalars(select(DrawingSheet).where(
            DrawingSheet.project_id == project_id).order_by(
            DrawingSheet.document_id, DrawingSheet.page))).all())
        sheet_ids = [s.id for s in sheets]
        items = list((await self.session.scalars(select(DrawingItem).where(
            DrawingItem.sheet_id.in_(sheet_ids)).order_by(DrawingItem.id))).all())
        work = await self.projects.work_items(project_id)
        current_fingerprint = fingerprint(work)
        links = await self.projects.documents_by_role(project_id, DocumentRole.DRAWING)
        documents = []
        for link in links:
            doc = await self.documents.get(link.document_id)
            if doc:
                documents.append({"id": str(doc.id), "filename": doc.filename,
                                  "indexed": any(s.document_id == doc.id for s in sheets)})
        item_rows, union = [], []
        linked = {str(w.id): [] for w in work}
        for item in items:
            status = item.review_status
            if status != "pending" and item.review_fingerprint != current_fingerprint:
                status = "stale"
            suggestions = [str(w.id) for w in work
                           if len(compact(item.name)) >= 2 and compact(item.name) in compact(w.name)]
            item_rows.append({
                "id": str(item.id), "sheet_id": str(item.sheet_id), "name": item.name,
                "evidence": item.evidence, "review_status": status,
                "work_item_ids": item.work_item_ids, "suggested_work_item_ids": suggestions,
                "review_note": item.review_note,
            })
            if status == "confirmed" and item.work_item_ids:
                for work_id in item.work_item_ids:
                    if work_id in linked:
                        linked[work_id].append(str(item.id))
            elif status != "rejected":
                union.append({"work_item_id": None, "item_no": None, "name": item.name,
                              "status": "drawing_only" if status == "confirmed" else "drawing_candidate",
                              "drawing_item_ids": [str(item.id)]})
        union = [{"work_item_id": str(w.id), "item_no": w.item_no, "name": w.name,
                  "status": "both" if linked[str(w.id)] else "needs_confirmation",
                  "drawing_item_ids": linked[str(w.id)]} for w in work] + union
        return {
            "revision": revision,
            "documents": documents,
            "sheets": [{"id": str(s.id), "document_id": str(s.document_id), "page": s.page,
                        "number": s.number, "title": s.title, "method": s.method,
                        "warning": s.warning, "evidence": s.evidence} for s in sheets],
            "items": item_rows, "union": union,
            "summary": {
                "pages": len(sheets), "unreadable_pages": sum(not s.number or not s.title for s in sheets),
                "unindexed_documents": sum(not d["indexed"] for d in documents),
                "work_items": len(work), "matched": sum(bool(v) for v in linked.values()),
                "pending_items": sum(i["review_status"] in ("pending", "stale") for i in item_rows),
            },
            "disclaimer": "以上為 AI／規則輔助的初步檢核結果，實際仍須依品管人員為主。"
                          "圖名候選不代表完整圖面內容；尚未找到對應不等於不存在。"
                          "竣工圖與契約圖的適用版本由使用者確認。",
        }
