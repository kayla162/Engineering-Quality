"""Local SQLite backup/verify/restore. Python standard library only.

The bundle is private data, not an encrypted archive or a signed artifact.
Stop uploads/deletions while backing up: SQLite snapshot consistency does not
make filesystem writes transactional.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys


class BackupError(ValueError):
    pass


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def readonly(path: Path):
    if not path.is_file():
        raise BackupError("Source database does not exist")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def check_database(path: Path):
    with closing(readonly(path)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign key check failed")


def documents(path: Path):
    with closing(readonly(path)) as connection:
        return connection.execute(
            "SELECT id, storage_path, file_hash FROM documents ORDER BY id"
        ).fetchall()


def safe_member(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupError("Invalid bundle path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise BackupError("Bundle path traversal rejected")
    candidate = root.joinpath(*path.parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise BackupError("Bundle path escapes root")
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise BackupError("Bundle links are not allowed")
    return candidate


def new_target(path: Path) -> Path:
    # mkdir without exist_ok is intentional: even an existing empty directory
    # is not a permitted destination.
    if path.exists() or path.is_symlink():
        raise BackupError("Destination must not already exist")
    target = path.absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    return target.resolve()


def remove_failed_target(target: Path):
    # Only called with the canonical directory that this invocation created.
    # Never follow a substituted symlink, junction or altered parent.
    if target.resolve() != target or target.is_symlink():
        raise BackupError("Refusing cleanup of a changed destination")
    if hasattr(target, "is_junction") and target.is_junction():
        raise BackupError("Refusing cleanup of a junction")
    shutil.rmtree(target)


def file_entry(root: Path, path: Path, kind: str) -> dict:
    return {"path": path.relative_to(root).as_posix(), "kind": kind,
            "size": path.stat().st_size, "sha256": digest(path)}


def copy_verified(source: Path, destination: Path):
    before = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if digest(destination) != before or digest(source) != before:
        raise BackupError("Source changed while copying")


def artifact_allowed(path: Path) -> bool:
    if any(part.startswith(".") for part in path.parts):
        return False
    if re.search(r"(secret|credential|password|token|private.?key)", path.name, re.I):
        return False
    return path.suffix.lower() in {".json", ".png", ".jpg", ".jpeg", ".webp", ".pdf",
                                  ".md", ".csv", ".txt"}


def backup(database: Path, output: Path, base_dir: Path, artifacts: list[Path]):
    database = database.resolve(strict=True)
    artifact_roots = [path.resolve(strict=True) for path in artifacts]
    if any(not path.is_dir() for path in artifact_roots):
        raise BackupError("Artifact source must be a directory")
    if any(output.resolve().is_relative_to(path) for path in artifact_roots):
        raise BackupError("Backup destination cannot be inside an artifact source")
    target = new_target(output)
    try:
        snapshot = target / "database.sqlite3"
        with closing(readonly(database)) as source, closing(sqlite3.connect(snapshot)) as dest:
            source.backup(dest)
            # backup() preserves the source WAL journal mode. Normalize only
            # the copied database so validation never needs unbundled sidecars.
            dest.execute("PRAGMA journal_mode=DELETE")
        check_database(snapshot)
        manifest = {"format": "engineering-quality-sqlite-backup", "version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": [file_entry(target, snapshot, "database")], "documents": []}
        for index, (doc_id, original_path, expected_hash) in enumerate(documents(snapshot)):
            source = Path(original_path)
            if not source.is_absolute():
                source = base_dir / source
            source = source.resolve(strict=True)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash or ""):
                raise BackupError("Document has no valid source hash")
            suffix = source.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ".bin"
            copied = target / "uploads" / f"{index:06d}{suffix}"
            copy_verified(source, copied)
            entry = file_entry(target, copied, "document")
            if entry["sha256"] != expected_hash.lower():
                raise BackupError("Uploaded file does not match document source hash")
            manifest["files"].append(entry)
            manifest["documents"].append({
                "id": doc_id, "original_path": original_path, "path": entry["path"],
                "source_sha256": expected_hash.lower(),
            })
        for index, root in enumerate(artifact_roots):
            for source in sorted(root.rglob("*")):
                relative = source.relative_to(root)
                if not artifact_allowed(relative):
                    continue
                source = safe_member(root, relative.as_posix())
                if source.is_file():
                    copied = target / "artifacts" / str(index) / relative
                    copy_verified(source, copied)
                    manifest["files"].append(file_entry(target, copied, "artifact"))
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        verify(target)
    except Exception:
        remove_failed_target(target)
        raise
    return {"status": "ok", "action": "backup", "files": len(manifest["files"]),
            "documents": len(manifest["documents"])}


def verify(bundle: Path) -> dict:
    root = bundle.resolve(strict=True)
    manifest_path = safe_member(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or manifest.get("format") != "engineering-quality-sqlite-backup"
            or manifest.get("version") != 1):
        raise BackupError("Unsupported manifest format")
    files = manifest.get("files")
    mapped_documents = manifest.get("documents")
    if not isinstance(files, list) or not isinstance(mapped_documents, list):
        raise BackupError("Invalid manifest entries")
    entries = {}
    for entry in files:
        path = safe_member(root, entry["path"])
        if entry["path"] in entries:
            raise BackupError("Duplicate manifest file")
        entries[entry["path"]] = entry
        if (not path.is_file() or path.stat().st_size != entry["size"]
                or digest(path) != entry["sha256"]):
            raise BackupError("Bundle file hash or size mismatch")
        kind = entry["kind"]
        if kind not in {"database", "document", "artifact"}:
            raise BackupError("Unknown bundle file kind")
        if kind == "database" and entry["path"] != "database.sqlite3":
            raise BackupError("Invalid database entry")
        if kind == "document" and not entry["path"].startswith("uploads/"):
            raise BackupError("Invalid document location")
        if kind == "artifact" and not entry["path"].startswith("artifacts/"):
            raise BackupError("Invalid artifact location")
    if sum(entry["kind"] == "database" for entry in files) != 1:
        raise BackupError("Bundle must have exactly one database")
    # Extra files (including injected SQLite WAL files) are never accepted.
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != set(entries) | {"manifest.json"}:
        raise BackupError("Bundle contains unlisted files")
    snapshot = root / "database.sqlite3"
    check_database(snapshot)
    rows = {str(row[0]): row for row in documents(snapshot)}
    seen_ids, seen_paths = set(), set()
    for document in mapped_documents:
        doc_id = str(document["id"])
        path = document["path"]
        safe_member(root, path)
        if doc_id in seen_ids or path in seen_paths:
            raise BackupError("Duplicate document mapping")
        seen_ids.add(doc_id)
        seen_paths.add(path)
        row = rows.get(doc_id)
        entry = entries.get(path)
        if (not row or not entry or entry["kind"] != "document"
                or row[1] != document["original_path"]
                or (row[2] or "").lower() != document["source_sha256"]
                or entry["sha256"] != document["source_sha256"]):
            raise BackupError("Document mapping does not match database")
    if seen_ids != set(rows) or seen_paths != {
        entry["path"] for entry in files if entry["kind"] == "document"
    }:
        raise BackupError("Incomplete document mapping")
    return manifest


def restore(bundle: Path, destination: Path):
    manifest = verify(bundle)
    target = new_target(destination)
    try:
        for entry in manifest["files"]:
            source = safe_member(bundle, entry["path"])
            copied = safe_member(target, entry["path"])
            copy_verified(source, copied)
            if digest(copied) != entry["sha256"]:
                raise BackupError("Bundle changed after verification")
        snapshot = target / "database.sqlite3"
        with closing(sqlite3.connect(snapshot)) as connection:
            with connection:
                for document in manifest["documents"]:
                    connection.execute(
                        "UPDATE documents SET storage_path = ? WHERE id = ?",
                        (str(safe_member(target, document["path"])), document["id"]),
                    )
        check_database(snapshot)
        report = {"status": "ok", "action": "restore",
                  "documents": len(manifest["documents"]),
                  "source_database_sha256": next(entry["sha256"] for entry in manifest["files"]
                                                  if entry["kind"] == "database"),
                  "restored_database_sha256": digest(snapshot),
                  "note": "Only documents.storage_path relocated in restored database"}
        (target / "restore-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    except Exception:
        remove_failed_target(target)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup", help="Snapshot full SQLite database and referenced uploads")
    create.add_argument("--database", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True, help="New, non-existing bundle directory")
    create.add_argument("--base-dir", type=Path, default=Path.cwd(),
                        help="Resolve relative document storage paths against this directory")
    create.add_argument("--artifacts", type=Path, action="append", default=[],
                        help="Optional inspection directory; repeat for more than one")
    check = commands.add_parser("verify", help="Verify bundle file hashes and database integrity")
    check.add_argument("--bundle", type=Path, required=True)
    recover = commands.add_parser("restore", help="Restore only into a new directory")
    recover.add_argument("--bundle", type=Path, required=True)
    recover.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = backup(args.database, args.output, args.base_dir, args.artifacts)
        elif args.command == "verify":
            manifest = verify(args.bundle)
            result = {"status": "ok", "action": "verify", "files": len(manifest["files"]),
                      "documents": len(manifest["documents"])}
        else:
            result = restore(args.bundle, args.target)
        print(json.dumps(result))
        return 0
    except BackupError as error:
        print(f"Backup operation failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # Do not print exception paths, document names, database contents or credentials.
        print("Backup operation failed: invalid source, bundle, or destination. "
              "Check file availability, SHA-256 integrity and a new destination.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
