"""Bind pre-existing private inspection reports to one local project.

Run from repository root:
  .venv/Scripts/python.exe scripts/create_drawing_inspection_manifest.py --project-id UUID

Reads SQLite and source PDFs only. Writes a new manifest inside ignored storage.
Never imports historical decisions or edits the report artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.drawing_inspection_service import INSPECTION_ROOT, REPORT_PATHS, safe_path
from app.schemas.drawing_inspection import InspectionManifest


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_manifest(project_id, database, root=INSPECTION_ROOT):
    project_id = uuid.UUID(str(project_id))
    reports = {key: json.loads(safe_path(root, relative).read_text("utf-8-sig"))
               for key, relative in REPORT_PATHS.items()}
    snapshot = json.loads((root / "candidate-register" / "snapshot.json").read_text("utf-8-sig"))
    if uuid.UUID(snapshot["project_id"]) != project_id:
        raise ValueError("candidate snapshot belongs to a different project")
    revision = reports["candidates"]["summary"]["revision"]
    if snapshot["revision"] != revision:
        raise ValueError("candidate report revision differs from source snapshot")
    documents = []
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        for book in ("architecture", "structure"):
            report = reports[book]
            if uuid.UUID(report["project_id"]) != project_id:
                raise ValueError("review report belongs to a different project")
            doc_id = uuid.UUID(report["document_id"])
            row = conn.execute("""
                SELECT d.file_hash, d.storage_path FROM documents d JOIN project_documents pd
                ON pd.document_id = d.id WHERE pd.project_id = ? AND d.id = ? AND pd.role = 'drawing'
                """, (project_id.hex, doc_id.hex)).fetchone()
            if row is None or row["file_hash"] != report["pdf_sha256"]:
                raise ValueError("document hash or project role mismatch")
            source = Path(row["storage_path"])
            if not source.is_absolute():
                source = ROOT / source
            if digest(source) != row["file_hash"]:
                raise ValueError("source PDF no longer matches document hash")
            documents.append({"id": str(doc_id), "file_hash": row["file_hash"], "book": book})
        conn.rollback()
    if reports["cross_check"]["source"]["pdf_sha256"] != documents[0]["file_hash"]:
        raise ValueError("cross-check refers to a different PDF")
    images = {}
    for index, sample in enumerate(reports["cross_check"].get("visual_samples", []), 1):
        # The old report uses ../ paths. Resolve only during explicit preparation,
        # then record a canonical path; the serving code rejects traversal entirely.
        image_path = (root / "cross-check" / sample["image"]).resolve()
        if not image_path.is_relative_to(root.resolve()) or image_path.suffix.lower() != ".png":
            raise ValueError("sample image outside private artifact root")
        relative = image_path.relative_to(root.resolve()).as_posix()
        safe_path(root, relative)
        if not image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("sample is not a PNG")
        images[f"sample-{index:03}"] = {
            "path": relative, "sha256": digest(image_path), "label": sample["label"],
        }
    manifest = InspectionManifest.model_validate({
        "version": 1, "project_id": str(project_id), "historical_revision": revision,
        "documents": documents,
        "artifacts": {key: {"path": relative, "sha256": digest(safe_path(root, relative))}
                      for key, relative in REPORT_PATHS.items()},
        "images": images,
    })
    output = safe_path(root, f"{project_id}/manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return output, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=uuid.UUID, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "app.db")
    args = parser.parse_args()
    output, manifest = build_manifest(args.project_id, args.database)
    print(json.dumps({"manifest": str(output), "historical_revision": manifest.historical_revision,
                      "documents": len(manifest.documents), "images": len(manifest.images)}))
