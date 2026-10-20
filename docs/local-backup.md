# 本機 SQLite 備份與還原

`scripts/backup_project.py` 僅使用 Python 標準函式庫，處理本機 SQLite。
Docker Compose 使用的 PostgreSQL 不適用此工具；須另外使用 PostgreSQL 的備份程序。

## 備份內容與限制

- 使用 SQLite backup API，包含已提交但尚在 WAL 的資料。保留完整資料表、人工覆核狀態與註記。
- 依快照內 `documents` 的引用複製上傳檔案，核對資料庫內原始 SHA-256。
  缺檔、來源雜湊不符或複製途中異動都會失敗，不產生可誤認為完整的備份目錄。
- `manifest.json` 記錄資料庫、文件、選擇性成果的相對位置、大小與 SHA-256，
  以及文件識別碼和原始儲存路徑；這份清單本身也是私人資料。
- `--artifacts` 可重複指定圖說核對成果資料夾。只複製 JSON、PNG、JPG、JPEG、WEBP、
  PDF、Markdown、CSV、TXT；略過隱藏檔案／目錄及檔名含 secret、credential、
  password、token、private-key 的檔案。不要把憑證資料夾當成果來源；
  工具不會檢查檔案內容是否包含密碼。
- 不自動收集 `.env`、專案程式、環境設定、下載索引或未被文件表引用的上傳檔案。
  另行記錄程式版本與安裝需求；秘密資料由既有安全管道管理。
- 備份不加密、不簽章。SHA-256 可驗證損壞，不能抵禦同時修改清單及內容的攻擊。
  備份應存於受控本機位置，不公開分享或加入版本控制。

SQLite 快照和檔案複製不是同一筆交易。執行前暫停上傳、刪除與背景分析，
並盡量在程式停止時備份；工具不會替你停止服務。

## 建立與驗證

在專案根目錄執行 PowerShell；每次使用新的目的地：

```powershell
.venv/Scripts/python.exe scripts/backup_project.py backup `
  --database data/app.db `
  --output storage/backups/local-20261020-01

.venv/Scripts/python.exe scripts/backup_project.py verify `
  --bundle storage/backups/local-20261020-01
```

選擇性加上 `--artifacts storage/your-inspection-directory`，可重複指定。
相對 `documents.storage_path` 預設以執行命令的工作目錄解析；
必要時加 `--base-dir C:/path/to/original/project`。
成功會輸出只含數量等資訊的 JSON，結束碼為 `0`；驗證或操作失敗為 `1`。

## 只還原到新的隔離目錄

```powershell
.venv/Scripts/python.exe scripts/backup_project.py restore `
  --bundle storage/backups/local-20261020-01 `
  --target storage/restore-rehearsal-20261020-01
```

目的地必須尚不存在，連既有空資料夾也拒絕。工具先驗證整份備份，再建立目的地；
禁止路徑穿越、檔案連結、未列入清單的額外檔案及不完整文件對應。

還原目錄包含：

```text
database.sqlite3
uploads/
artifacts/0/       # 僅在有指定成果資料夾時存在，後續來源依序為 1、2…
restore-report.json
```

只有副本的 `documents.storage_path` 改成新 `uploads` 位置的絕對路徑；
原資料庫、原上傳檔案及備份包不修改。
`restore-report.json` 保留來源和還原後資料庫雜湊。因路徑已改寫，兩者雜湊通常不同。
還原目錄不是原始備份包，請對原始包執行 `verify`。

成果檔案內容不重寫。成果服務目前只有 `DrawingInspectionService(root=...)`
建構參數可指定核對根目錄，尚無環境變數入口。隔離服務測試時可注入
`artifacts/0` 等對應目錄；單純還原檔案不會自動切換 Web API 的成果來源。
啟動隔離後端時指定新 SQLite 與上傳目錄，
確認文件可開啟、人工狀態和數量一致。此工具不切換正式環境設定、不覆蓋正式資料，
也不代替人工驗收。

## Docker 選配本機 OCR

預設 `INSTALL_OCR=false`，不安裝 OCR 依賴：

```powershell
docker compose build backend
```

明確啟用：

```powershell
docker compose build --build-arg INSTALL_OCR=true backend
```

也可在目前終端設定 `$env:INSTALL_OCR = "true"` 後建置。
啟用時安裝 `requirements-ocr.txt` 的 RapidOCR，以及 Linux 的 `libgl1`、
`libglib2.0-0`、`libgomp1`。OCR 套件及權重在建置期間安裝，圖說處理在本機容器內執行。
不啟動付費 API；既有 LLM 執行期選項需依自己的離線設定維持停用。

`.dockerignore` 排除本機私人 storage、資料庫與 sidecar、環境檔／秘密檔、
下載索引與快取。法規索引及上傳文件使用執行期 volume，不烘焙進映像檔。
`docker compose config --quiet` 只驗證設定語法；實際映像建置、OCR import 與容器
運行必須另外驗證，不能只以語法檢查宣稱完成。
