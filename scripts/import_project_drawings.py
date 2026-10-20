"""Local import through the same services as the API; skips existing indexes by default."""
import argparse
import asyncio
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from starlette.datastructures import UploadFile
from app.core.db import get_session_factory, dispose_engine
from app.core.errors import DuplicateFileError
from app.core.enums import DocumentRole
from app.schemas.drawing import IndexDrawing
from app.services.document_service import DocumentService
from app.services.drawing_service import DrawingService
from app.services.project_service import ProjectService


async def run(args):
    async with get_session_factory()() as session:
        projects = ProjectService(session)
        existing = [p for p in await projects.list_projects() if p.name == args.name]
        if len(existing) > 1:
            raise RuntimeError("同名專案不只一個，請在畫面指定專案後匯入")
        project = existing[0] if existing else await projects.create_project(args.name)
        project_id = project.id
        print(f"project_id={project_id}", flush=True)
        for path in args.pdf:
            service = DocumentService(session)
            with path.open("rb") as handle:
                try:
                    doc = await service.upload_stream(UploadFile(handle, filename=path.name))
                    doc_id = doc.id
                except DuplicateFileError as exc:
                    doc_id = uuid.UUID(exc.details["document_id"])
            if await projects.projects.get_link(project_id, doc_id) is None:
                await projects.attach_document(project_id, doc_id, DocumentRole.DRAWING)
            drawings = DrawingService(session)
            snapshot = await drawings.snapshot(project_id)
            if any(d["id"] == str(doc_id) and d["indexed"] for d in snapshot["documents"]):
                print("already indexed; preserved", flush=True)
                continue
            print("indexing...", flush=True)
            result = await drawings.index(project_id, IndexDrawing(
                document_id=doc_id, use_ocr=args.ocr, expected_revision=snapshot["revision"]))
            print(result["summary"], flush=True)
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("pdf", type=Path, nargs="+")
    asyncio.run(run(parser.parse_args()))
