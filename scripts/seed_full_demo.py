"""一鍵建立「完整示範專案」：匯入示範企業內部文件清單，上傳 data/samples/full_demo/ 的七份假資料文件、
設定角色，逐份分析規範與契約的法規引用，再建立工項與檢核表。後端要先跑起來。

SQLite 同時只能有一個寫入者：分析是背景任務，所以每份分析完才做下一步，不然會「database is locked」。

    python scripts/generate_full_demo.py          # 先產生文件（已產生過可略過）
    python scripts/seed_full_demo.py --username admin --password '...'

帳號密碼也可以用環境變數 DEMO_USERNAME / DEMO_PASSWORD。同一份檔案重跑不會重複上傳
（系統以內容去重），專案則每次新建一個，名稱帶時間。
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_full_demo import FILES, OUT, PROJECT, build  # noqa: E402

ENTERPRISE_DEMO = ROOT / "data" / "samples" / "enterprise_documents_demo.xlsx"
#: 這兩份的法規引用要分析（總覽與引用清單才有東西看）
ANALYZE = ("施工規範_完整示範.pdf", "契約書_完整示範.docx")
MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


def _check(response: httpx.Response, what: str) -> dict:
    if response.status_code >= 400:
        raise SystemExit(f"{what}失敗（HTTP {response.status_code}）：{response.text[:300]}")
    return response.json() if response.content else {}


def upload(client: httpx.Client, path: Path) -> str:
    files = {"file": (path.name, path.read_bytes(), MIME[path.suffix])}
    response = client.post("/api/documents/upload", files=files)
    if response.status_code == 409:
        return response.json()["error"]["details"]["document_id"]
    return _check(response, f"上傳 {path.name} ")["document_id"]


def wait_for_job(client: httpx.Client, job_id: str, timeout: float = 600) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _check(client.get(f"/api/jobs/{job_id}"), "查詢分析進度")
        if job.get("status") in ("COMPLETED", "FAILED"):
            return job["status"] if job["status"] == "COMPLETED" else f"FAILED：{job.get('error_message', '')[:120]}"
        time.sleep(2)
    return "逾時"


def seed(base_url: str, username: str, password: str, origin: str) -> str:
    if not all((OUT / name).exists() for name in FILES):
        build()
    with httpx.Client(base_url=base_url, headers={"Origin": origin}, timeout=900) as client:
        _check(client.post("/api/auth/login", json={"username": username, "password": password}), "登入")
        # 企業內部文件來源沒有清單時，畫面會一直顯示「來源尚未就緒」；先匯入示範清單
        imported = client.post(
            "/api/enterprise-documents/import",
            files={"file": (ENTERPRISE_DEMO.name, ENTERPRISE_DEMO.read_bytes(), MIME[".xlsx"])},
        )
        _check(imported, "匯入示範企業內部文件清單")
        print(f"  企業內部文件清單（示範）：{imported.json().get('total')} 份")
        name = f"{PROJECT}（{datetime.now():%m/%d %H:%M}）"
        project_id = _check(client.post("/api/projects", json={"name": name}), "建立專案")["project_id"]
        for filename, (role, _builder) in FILES.items():
            document_id = upload(client, OUT / filename)
            _check(
                client.post(f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}),
                f"設定 {filename} 的角色",
            )
            print(f"  {filename} → {role}")
            if filename in ANALYZE:
                job = _check(client.post(f"/api/documents/{document_id}/analyze"), f"分析 {filename} ")
                status = wait_for_job(client, job["job_id"])
                print(f"    法規引用分析：{status}")
        _check(client.post(f"/api/projects/{project_id}/work-items"), "建立工項")
        print("  建立檢核表（水電圖是掃描檔，OCR 需要約半分鐘）…")
        summary = _check(client.post(f"/api/projects/{project_id}/checklist"), "建立檢核表")
    print(f"完成：{name}")
    print(f"  工項 {summary.get('total')} 項；摘要 {summary.get('summary')}")
    return project_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("DEMO_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.environ.get("DEMO_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"))
    parser.add_argument("--origin", default="http://localhost:5173", help="要在 CORS_ORIGINS 裡")
    args = parser.parse_args()
    if not args.username or not args.password:
        parser.error("要給 --username 與 --password（或 DEMO_USERNAME / DEMO_PASSWORD）")
    seed(args.base_url, args.username, args.password, args.origin)
    print("  打開前端，到「專案」分頁選這個專案。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
