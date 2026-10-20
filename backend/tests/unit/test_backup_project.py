"""Exercise the standalone backup CLI against real SQLite/filesystem fixtures."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backup_project.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8",
    )


@pytest.fixture
def source(tmp_path):
    upload = tmp_path / "original" / "drawing.pdf"
    upload.parent.mkdir()
    upload.write_bytes(b"private drawing fixture")
    database = tmp_path / "live.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, storage_path TEXT, file_hash TEXT)"
        )
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?)",
            ("doc-1", str(upload), hashlib.sha256(upload.read_bytes()).hexdigest()),
        )
        connection.execute("CREATE TABLE reviews (status TEXT, note TEXT)")
        connection.execute("INSERT INTO reviews VALUES ('pending', 'keep manual data')")
    return database, upload


def make_backup(source, tmp_path, *extra):
    database, _ = source
    bundle = tmp_path / "backup"
    result = run_cli("backup", "--database", database, "--output", bundle, *extra)
    assert result.returncode == 0, result.stderr
    return bundle


def test_round_trip_preserves_manual_rows_and_relocates_only_restored_database(source, tmp_path):
    database, upload = source
    original_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    bundle = make_backup(source, tmp_path)
    assert run_cli("verify", "--bundle", bundle).returncode == 0
    restored = tmp_path / "restored"
    result = run_cli("restore", "--bundle", bundle, "--target", restored)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(restored / "database.sqlite3") as connection:
        path = Path(connection.execute("SELECT storage_path FROM documents").fetchone()[0])
        assert path.is_relative_to(restored)
        assert path.read_bytes() == upload.read_bytes()
        assert connection.execute("SELECT * FROM reviews").fetchall() == [
            ("pending", "keep manual data")
        ]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == original_hash
    assert run_cli("verify", "--bundle", bundle).returncode == 0


@pytest.mark.parametrize("kind", ["database", "document"])
def test_corruption_is_rejected_before_destination_is_created(source, tmp_path, kind):
    bundle = make_backup(source, tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["kind"] == kind)
    with (bundle / entry["path"]).open("ab") as handle:
        handle.write(b"corruption")
    target = tmp_path / "restored"
    assert run_cli("verify", "--bundle", bundle).returncode != 0
    assert run_cli("restore", "--bundle", bundle, "--target", target).returncode != 0
    assert not target.exists()


@pytest.mark.parametrize("nonempty", [False, True])
def test_restore_refuses_any_existing_destination(source, tmp_path, nonempty):
    bundle = make_backup(source, tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    if nonempty:
        (target / "keep.txt").write_text("never overwrite")
    result = run_cli("restore", "--bundle", bundle, "--target", target)
    assert result.returncode != 0
    assert sorted(p.name for p in target.iterdir()) == (["keep.txt"] if nonempty else [])


@pytest.mark.parametrize("evil", ["../outside", "/absolute", "C:/outside", "uploads/../../outside",
                                 r"uploads\..\outside"])
def test_manifest_path_traversal_is_rejected(source, tmp_path, evil):
    bundle = make_backup(source, tmp_path)
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"][1]["path"] = evil
    path.write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "restore"
    assert run_cli("restore", "--bundle", bundle, "--target", target).returncode != 0
    assert not target.exists()


def test_source_must_match_document_hash_and_failed_backup_is_removed(source, tmp_path):
    database, upload = source
    upload.write_bytes(b"changed after import")
    output = tmp_path / "backup"
    result = run_cli("backup", "--database", database, "--output", output)
    assert result.returncode != 0
    assert not output.exists()


def test_missing_upload_fails_without_modifying_source(source, tmp_path):
    database, upload = source
    before = database.read_bytes()
    upload.unlink()
    output = tmp_path / "backup"
    assert run_cli("backup", "--database", database, "--output", output).returncode != 0
    assert not output.exists()
    assert database.read_bytes() == before


def test_optional_artifacts_exclude_environment_and_secret_files(source, tmp_path):
    artifacts = tmp_path / "inspection"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text('{"project_id": "test"}')
    (artifacts / "crop.png").write_bytes(b"image fixture")
    (artifacts / ".env").write_text("TOKEN=private")
    (artifacts / "credentials.json").write_text('{"token":"private"}')
    bundle = make_backup(source, tmp_path, "--artifacts", artifacts)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    names = [Path(entry["path"]).name for entry in manifest["files"]]
    assert "crop.png" in names and "manifest.json" in names
    assert ".env" not in names and "credentials.json" not in names


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    assert run_cli("backup", "--database", missing, "--output", tmp_path / "out").returncode == 1
    assert not missing.exists()


def test_live_wal_commits_are_included_in_snapshot(source, tmp_path):
    database, _ = source
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO reviews VALUES ('confirmed', 'committed in WAL')")
        connection.commit()
        assert Path(str(database) + "-wal").exists()
        bundle = make_backup(source, tmp_path)
        with sqlite3.connect(bundle / "database.sqlite3") as snapshot:
            assert snapshot.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2
    finally:
        connection.close()


def test_document_mapping_cannot_be_redirected_to_another_bundle_file(source, tmp_path):
    bundle = make_backup(source, tmp_path)
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["documents"][0]["path"] = "database.sqlite3"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "restore"
    assert run_cli("restore", "--bundle", bundle, "--target", target).returncode == 1
    assert not target.exists()


def test_backup_refuses_existing_destination_without_modifying_it(source, tmp_path):
    database, _ = source
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_bytes(b"keep")
    assert run_cli("backup", "--database", database, "--output", target).returncode == 1
    assert marker.read_bytes() == b"keep"


def test_unlisted_wal_in_bundle_is_rejected(source, tmp_path):
    bundle = make_backup(source, tmp_path)
    (bundle / "database.sqlite3-wal").write_bytes(b"unexpected SQLite sidecar")
    assert run_cli("verify", "--bundle", bundle).returncode == 1
