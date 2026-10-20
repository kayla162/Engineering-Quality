"""Read existing local reports without importing their historical decisions."""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.config import PROJECT_ROOT
from app.models.document import Document
from app.models.project import ProjectDocument
from app.schemas.drawing_inspection import InspectionManifest
from app.services.drawing_service import DrawingService

INSPECTION_ROOT = PROJECT_ROOT / "storage" / "drawing-inspection"
REPORT_PATHS = {
    "candidates": "candidate-register/candidate-register.json",
    "cross_check": "cross-check/cross-check.json",
    "architecture": "architecture-review/reviewed-pages.json",
    "structure": "structure-review/reviewed-pages.json",
}
HISTORY_WARNING = "歷史核對成果為 AI 輔助快照，非人工確認或工程結論；名稱分組及人工狀態來自目前資料庫。"


def safe_path(root: Path, relative: str) -> Path:
    """Only canonical forward-slash relative paths inside the private root."""
    part = PurePosixPath(relative)
    if (not relative or "\\" in relative or ":" in relative or part.is_absolute()
            or any(p in (".", "..") for p in relative.split("/"))):
        raise ValueError("invalid private artifact path")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("private artifact escaped root")
    return resolved


def checked_bytes(root, binding):
    path = safe_path(root, binding.path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != binding.sha256:
        raise ValueError("private artifact changed")
    return data


def name_key(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).upper()


def document_url(project_id, document_id, page):
    return f"/api/projects/{project_id}/drawings/documents/{document_id}/file#page={page}"


def current_groups(project_id, snapshot):
    sheets = {s["id"]: s for s in snapshot["sheets"]}
    grouped = {}
    for item in snapshot["items"]:
        key = name_key(item["name"])
        group = grouped.setdefault(key, {
            "id": "name-" + hashlib.sha256(key.encode()).hexdigest()[:16],
            "key": key, "names": [], "items": [],
        })
        if item["name"] not in group["names"]:
            group["names"].append(item["name"])
        sheet = sheets[item["sheet_id"]]
        group["items"].append({
            **{k: item[k] for k in ("id", "name", "sheet_id", "review_status", "review_note")},
            **{k: sheet[k] for k in ("document_id", "page", "number", "title")},
            "document_url": document_url(project_id, sheet["document_id"], sheet["page"]),
        })
    for group in grouped.values():
        group["occurrence_count"] = len(group["items"])
        group["page_count"] = len({i["sheet_id"] for i in group["items"]})
    return sorted(grouped.values(), key=lambda g: (-g["occurrence_count"], g["key"]))


def load_reports(root, project_id):
    manifest = InspectionManifest.model_validate_json(
        safe_path(root, f"{project_id}/manifest.json").read_bytes())
    if manifest.project_id != project_id or set(manifest.artifacts) != set(REPORT_PATHS):
        raise ValueError("invalid manifest binding")
    reports = {}
    for key, relative in REPORT_PATHS.items():
        binding = manifest.artifacts[key]
        if binding.path != relative:
            raise ValueError("report outside exact whitelist")
        reports[key] = json.loads(checked_bytes(root, binding))
        if not isinstance(reports[key], dict):
            raise ValueError("invalid report")
    candidates, cross = reports["candidates"], reports["cross_check"]
    if not isinstance(candidates.get("summary"), dict):
        raise ValueError("missing historical summary")
    if candidates["summary"].get("revision") != manifest.historical_revision:
        raise ValueError("historical revision mismatch")
    collections = [candidates.get("suggestions"), cross.get("references"),
                   cross.get("index", {}).get("rows"),
                   reports["architecture"].get("rows"), reports["structure"].get("rows")]
    if any(not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
           for rows in collections):
        raise ValueError("invalid report rows")
    for row in cross["references"] + cross["index"]["rows"]:
        if not isinstance(row.get("targets", []), list):
            raise ValueError("invalid target list")
        if row.get("source_page") is not None and not isinstance(row["source_page"], int):
            raise ValueError("invalid source page")
    for key, binding in manifest.images.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", key):
            raise ValueError("invalid image identifier")
        path = safe_path(root, binding.path)
        if path.suffix.lower() != ".png" or not checked_bytes(root, binding).startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("invalid sample image")
    return manifest, reports


class DrawingInspectionService:
    def __init__(self, session, root=None):
        self.session = session
        self.root = root if root is not None else INSPECTION_ROOT

    async def _bound_reports(self, project_id):
        try:
            manifest, reports = await run_in_threadpool(load_reports, self.root, project_id)
            docs = (await self.session.execute(select(Document.id, Document.file_hash).join(
                ProjectDocument, ProjectDocument.document_id == Document.id).where(
                    ProjectDocument.project_id == project_id, ProjectDocument.role == "drawing"))).all()
            actual = {str(did): digest for did, digest in docs}
            expected = {str(d.id): d.file_hash for d in manifest.documents}
            if (actual != expected or len(expected) != len(manifest.documents)
                    or len({d.book for d in manifest.documents}) != len(manifest.documents)):
                return None
            return manifest, reports
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ValidationError):
            return None

    async def snapshot(self, project_id):
        snapshot = await DrawingService(self.session).snapshot(project_id)
        groups = current_groups(project_id, snapshot)
        result = {
            "project_id": str(project_id), "available": False,
            "revision": snapshot["revision"], "historical_revision": None,
            "warnings": [HISTORY_WARNING],
            "summary": {
                "current_candidates": len(snapshot["items"]), "current_name_groups": len(groups),
                "current_statuses": dict(Counter(i["review_status"] for i in snapshot["items"])),
                "historical_name_groups": 0, "historical_similar_hints": 0,
                "index_title_differences": 0, "references": 0, "reference_counts": {},
            },
            "historical_summary": {}, "groups": groups, "similar_hints": [],
            "findings": [], "images": [],
        }
        bound = await self._bound_reports(project_id)
        if not bound:
            result["warnings"].append("尚未建立有效的專案核對成果，或來源已變更／缺檔；目前人工狀態仍可查閱。")
            return result
        manifest, reports = bound
        candidates, cross = reports["candidates"], reports["cross_check"]
        books = {d.book: str(d.id) for d in manifest.documents}
        architecture_id = books.get("architecture")
        differences = [r for r in cross["index"]["rows"]
                       if r.get("title_comparison") == "different_text_requires_review"]
        findings = []
        for kind, rows in (("index_title_difference", differences), ("reference", cross["references"])):
            for index, row in enumerate(rows):
                classification = row.get("classification", kind)
                priority = ("high" if classification in (
                    "not_located_requires_review", "ambiguous_sheet_variant") else
                    "info" if classification in ("located_exact", "located_other_available_book") else "medium")
                page = row.get("source_page")
                findings.append({
                    "id": f"{kind}-{index}", "kind": classification, "priority": priority,
                    "source_page": page, "source_number": row.get("source_number", row.get("number")),
                    "title": row.get("token", row.get("index_title", "")),
                    "message": row.get("explanation", "目錄圖名與圖框文字不同，待人工核對"),
                    "quote": row.get("quote", ""), "document_id": architecture_id,
                    "document_url": document_url(project_id, architecture_id, page) if architecture_id else None,
                    "targets": [{k: t.get(k) for k in ("book", "page", "number", "title")}
                                for t in row.get("targets", []) if isinstance(t, dict)],
                })
        hints = [{k: row.get(k) for k in
                  ("left", "right", "left_name", "right_name", "reason", "similarity", "decision")}
                 for row in candidates["suggestions"]]
        # Do not expose report paths, historical item review_status or arbitrary HTML.
        result.update(available=True, historical_revision=manifest.historical_revision,
                      similar_hints=hints, findings=findings,
                      historical_summary={
                          **candidates["summary"],
                          "architecture_reviewed_pages": len(reports["architecture"]["rows"]),
                          "structure_reviewed_pages": len(reports["structure"]["rows"]),
                      },
                      images=[{"id": key, "label": value.label,
                               "url": f"/api/projects/{project_id}/drawing-inspection/images/{key}"}
                              for key, value in manifest.images.items()
                              if re.fullmatch(r"[a-zA-Z0-9_-]+", key)])
        result["summary"].update(
            historical_name_groups=candidates["summary"].get("normalized_name_groups", 0),
            historical_similar_hints=len(hints), index_title_differences=len(differences),
            references=len(cross["references"]), reference_counts=cross.get("reference_counts", {}))
        if snapshot["revision"] != manifest.historical_revision:
            result["warnings"].append("目前圖說版本與歷史快照不同；疑義及近似提示尚未重新產生。")
        return result

    async def image(self, project_id, image_id):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", image_id):
            raise HTTPException(404, "找不到核對影像")
        bound = await self._bound_reports(project_id)
        if not bound or image_id not in bound[0].images:
            raise HTTPException(404, "找不到核對影像")
        binding = bound[0].images[image_id]
        try:
            data = await run_in_threadpool(checked_bytes, self.root, binding)
            path = safe_path(self.root, binding.path)
            if path.suffix.lower() != ".png" or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("not a PNG")
            return path
        except (OSError, ValueError):
            raise HTTPException(404, "找不到核對影像") from None
