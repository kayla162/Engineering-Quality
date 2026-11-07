# 完整操作手冊

> 這份手冊收錄各功能的詳細操作、設定與實測紀錄。專案簡介請看 [README](../README.md)。

上傳工程文件（DOCX / PDF / TXT），系統會抽出文件中引用的法規、標準與施工規範，
查詢它們目前的狀態，並清楚標示哪些項目需要人工確認，最後匯出可稽核的報告。

設計文件：[架構](architecture.md)｜[資料庫](database.md)｜[API](api.md)｜[開發計畫](development-plan.md)

## 法規資料來源

系統支援下列來源，用 `REGULATION_SOURCES` 切換（逗號分隔，**順序即優先順序**）：

| 來源 | 內容 | 可信度 |
|---|---|---|
| `taiwan_law` | 法務部**全國法規資料庫** Open API：法律約 1,346 筆、法規命令約 10,447 筆 | 官方資料 |
| `pcces` | 工程會**公共工程施工綱要規範**目錄，315 章（含已刪除章節） | 官方資料 |
| `admin_rules` | `data/admin_rules.json` 的**行政規則與地方法規目錄**：全國法規資料庫沒收的工程會／內政部「要點」「綱要」、新北市自治條例與市府要點，共 13 部 | **示範目錄**：名稱取自秀山分隊的真實文件；只有「建築物無障礙設施設計規範」的日期核對過 PDF，其餘狀態與日期是假資料，每筆都寫明出處 |
| `enterprise` | 各租戶匯入的**企業內部文件清單**（品質手冊、程序書、作業標準、公司版規範、業主特訂條款） | 公司自己的資料，正確性由提供清單的單位負責 |
| `standards_demo` | `data/demo_standards.json` 的示範標準目錄（CNS/ISO/ASTM），含最新版次與廢止 | **假資料，僅供 Demo**：示範「標準有資料來源時」怎麼判定版次 |
| `mock` | `data/mock_regulations.json` 的假資料，補官方資料庫沒有的 CNS/施工規範 | **僅供 Demo，不可作為查核依據** |

`taiwan_law` 使用前要先建立本地索引：

```bash
python scripts/sync_taiwan_law.py
```

然後在 `.env` 設定：

```bash
REGULATION_SOURCES=taiwan_law
```

`pcces` 也要先同步（315 章、約 38 KB、十幾秒）：

```bash
python scripts/sync_pcces.py
```

想同時用假資料補 CNS/ISO 等項目（Demo 用途）就設 `taiwan_law,pcces,mock`。順序即優先序：官方法規 > 官方規範 > 假資料。

**忘記跑同步會怎樣？** 系統不會安靜地失敗。`GET /api/sources` 會回報哪個來源沒就緒、原因與要跑的命令，前端會在畫面最上方顯示警告橫幅；每一筆查不到的引用也會在「比對理由」寫出同一個命令。跑完同步後重新整理即可，不必重啟服務。
官方資料永遠優先，不會被假資料覆蓋。

**資料來源標示**：報告與 UI 的每一筆都會顯示 `data_source`（`taiwan_law` 或 `mock`），
`mock` 會額外標註「假資料，僅供 Demo，務必人工查證」。

**授權**：全國法規資料庫採 **政府資料開放授權條款第 1 版**（GODL v1.0，等同 CC BY 4.0），
可商業利用，但**必須註明出處**：「資料來源：法務部全國法規資料庫」。

### 為什麼是「同步」而不是「即時查詢」

法務部的 Open API 只提供**整包 ZIP 下載**，沒有「查單一法規」的 endpoint：

| Endpoint | 內容 | 大小 |
|---|---|---|
| `GET https://law.moj.gov.tw/api/Ch/Law/JSON` | `ChLaw.json.zip`，中文法律 | 約 6 MB |
| `GET https://law.moj.gov.tw/api/Ch/Order/JSON` | `ChOrder.json.zip`，中文命令 | 約 25 MB |
| `GET https://law.moj.gov.tw/api/En/Law/JSON` | 英譯法律 | — |
| `GET https://law.moj.gov.tw/api/En/Order/JSON` | 英譯命令 | — |

回傳的是 ZIP（不是 JSON body），內含 `{名稱}.json` + `schema.csv`（官方欄位定義）+ `manifest.csv`。
JSON 結構是 `{"UpdateDate": "...", "Laws": [...]}`。

如果每比對一筆引用就打一次 API，等於每筆下載 31 MB，完全不可行。
所以 `scripts/sync_taiwan_law.py` 先把它同步成本地索引（約 4 MB），
`TaiwanLawSource` 再從索引查詢——對上層的 `RegulationSource` 介面完全一樣。

**官方欄位 → 系統狀態的對應**（欄位定義來自 ZIP 內的 `schema.csv`）：

| 官方欄位 | 條件 | 系統狀態 |
|---|---|---|
| `LawAbandonNote` | 等於 `"廢"` | `REPEALED` |
| `LawEffectiveDate` | 日期在未來（修正條文尚未生效） | `AMENDED` |
| — | 其餘 | `ACTIVE` |

刻意不把「曾經修正過」一律當成 `AMENDED`——幾乎每部法規都修正過，那樣標示等於沒有標示。

---

## 快速開始

### 方式一：Docker（推薦）

```bash
cp .env.example .env && docker compose up --build
```

啟動後開啟 <http://localhost:3000>。後端 API 文件在 <http://localhost:8000/docs>。
`.env.example` 的 cookie 設定適用於本機 HTTP；正式部署請設 `AUTH_COOKIE_SECURE=true` 並在 HTTPS 後方提供服務。

後端容器啟動時會自動跑 migration 並載入種子資料，不需要額外步驟。

第一次使用前，先在後端環境建立首位管理員（資料庫 migration 必須已完成）：

```bash
docker compose exec backend python scripts/bootstrap_admin.py --tenant-name "預設租戶" --username admin
```

命令會以隱藏輸入方式要求設定至少 12 個字元的密碼。此部署已有有效管理員時，命令會拒絕重複建立；之後由租戶管理員登入「使用者管理」新增成員。

若管理員忘記密碼，具資料庫操作權限的部署人員可透過互動式命令重設。命令會撤銷既有 session、要求下次登入更改密碼，且不會啟用已停用帳號：

```bash
docker compose exec backend python scripts/reset_user_password.py --username admin
```

登入限流狀態由資料庫共享，讓多個後端 worker 使用同一個帳號/IP 時間窗。新資料庫 migration `0007` 會建立暫存限流資料表；SQLite 會序列化寫入，正式多 worker 部署建議使用 PostgreSQL。

### 方式二：本機開發

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

（Linux / macOS 用 `.venv/bin/pip`）

```bash
cp .env.example .env
```

`.env` 若不想安裝 PostgreSQL，把 `DATABASE_URL` 改成 `sqlite+aiosqlite:///./data/app.db` 即可。

```bash
.venv/Scripts/python -m alembic upgrade head
```

建立首位管理員（資料庫 migration 必須已完成）：

```bash
.venv/Scripts/python scripts/bootstrap_admin.py --tenant-name "預設租戶" --username admin
```

本機以 HTTP 開發時，請在 `.env` 將 `AUTH_COOKIE_SECURE=false`；正式環境必須使用 HTTPS 並保持 `AUTH_COOKIE_SECURE=true`。

```bash
.venv/Scripts/python scripts/seed_data.py
```

```bash
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload
```

另開一個終端機跑前端（開發模式會自動把 `/api` 轉給 `localhost:8000`）：

```bash
npm install --prefix frontend && npm run dev --prefix frontend
```

前端在 <http://localhost:5173>。

### 接官方法規資料庫

```bash
python scripts/sync_taiwan_law.py --keep-raw
```

`--keep-raw` 會把原始 ZIP 留在 `data/taiwan_law_cache/`，供稽核與日後做 RAG 使用。
索引本身（`data/taiwan_law_index.json`，約 4MB）是產生出來的，不進版控。

Docker 環境下，若 `REGULATION_SOURCES` 含 `taiwan_law` 且索引不存在，
容器第一次啟動會自動同步；索引存在具名 volume，重建映像檔不必重新下載。
手動重新同步：

```bash
docker compose exec backend python scripts/sync_taiwan_law.py --output /app/data/generated/taiwan_law_index.json
```

### 掃描版 PDF（OCR）

可選取文字不足（每頁少於 200 字）又有圖片的頁，會送 OCR 辨識。用的是 PyMuPDF 內建的
Tesseract 引擎，**不需要另外安裝 Python 套件或 `tesseract` 執行檔，只需要語言資料**
（預設 `chi_tra+eng`）。

- **Docker**：映像檔已裝好 `tesseract-ocr-chi-tra`，不必設定。
- **Windows 本機**：Tesseract 安裝程式只附英文語言檔。把
  [`chi_tra.traineddata`](https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_tra.traineddata)
  和 `eng.traineddata` 放到同一個資料夾（例如 `%LOCALAPPDATA%\tessdata`），在 `.env` 設
  `TESSDATA_PATH` 指向它。裝好後重新分析即可，不必重啟服務。

OCR 讀出來的內容一律標示：文件清單顯示「解析品質不佳：N 頁以 OCR 辨識」，詳細面板的原始段落旁註明
「由 OCR 辨識，可能有錯字」。**辨識錯字會讓比對安靜地變成 `NOT_FOUND` 或 `POSSIBLE_MATCH`**——
以 `sample_quality_plan_scanned.pdf` 實測，文字版抽得到 26 筆引用，掃描版抽到 24 筆，
漏了表格裡的 `ASTM C39` 與 `ISO 14001`，並把「營造安全衛生設施標準」讀成「安全衛生設施標準」。

OCR 不能用（沒有語言資料、或 `ENABLE_OCR=false`）時：整份沒有文字會報錯並寫出原因；
只有部分頁讀不到，就照常分析，原因附在解析品質說明裡。

### 企業內部文件（企業知識庫）

工程文件常引用公司自己的品質手冊、程序書、作業標準，官方資料庫查不到。`enterprise` 來源讓
各租戶匯入自己的文件管制一覽表（只要目錄：編號、名稱、版次、狀態，不要全文），之後：

- 用**文件名稱、別名或文件編號**（例如「QP-07-03」）引用的內部文件都抽得到——規則引擎只認得
  法規字尾，「品質手冊」「程序書」與文件編號原本完全抽不到，匯入的清單會加進該租戶的抽取字典。
- 依清單狀態判定：現行 → 現行有效、已修訂 → 已修正、作廢 → 已廢止。
- 重新匯入後跑法規異動檢查，改版或作廢的內部文件會列出受影響的文件。
- 清單依租戶隔離，別家公司的內部文件不會出現在你的比對裡。

**怎麼匯入**：租戶管理員在「總覽」的「企業內部文件」下載範本、填好後上傳；或用命令：

```bash
.venv/Scripts/python scripts/import_enterprise_documents.py <清單.xlsx> --tenant <租戶名稱>
```

匯入是**整份取代、全有或全無**：任何一列有錯（必填欄空白、狀態不是三選一、文件編號重複…）
整份不收，並逐列列出錯誤。記得在 `.env` 的 `REGULATION_SOURCES` 加上 `enterprise`。

**沒有真實清單時**，可以先用假資料試：`data/samples/enterprise_documents_demo.xlsx` 是虛構的
「示範營造股份有限公司」的 12 份內部文件（含作廢、已修訂、只用編號或別名引用的情況），
搭配 `data/samples/sample_quality_plan_enterprise.txt` 分析，共 13 筆引用：11 筆內部文件
（8 現行有效、2 已修正、1 已廢止）與 2 筆官方法規。範本與假資料都由
`scripts/generate_enterprise_template.py`（`--demo`）產生。

**名稱真實、編號假的清單**：`data/samples/enterprise_documents_xiushan.xlsx` 是從秀山分隊的
「整體品質計畫」抽出的 211 份承攬廠商自有文件（品質管理標準、施工要領、自主檢查表、紀錄表），
其中 138 份計畫書註明「於分項施工計畫內訂定」。計畫書沒有文件編號、版次與生效日，這三欄是假資料
（`XS-QS-01` 這類編號），狀態一律「現行」。重新產生：

```bash
.venv/Scripts/python scripts/generate_enterprise_template.py --from-quality-plan 工程文書/整體品質計畫.docx
```

拿真實計畫書分析（`REGULATION_SOURCES` 含 `enterprise`）：匯入前 174 筆引用只有 14 筆判為現行；
匯入後抽到 388 筆、327 筆現行、36 筆查無。查無的多半是監造單位的表單（「監造單位鋼筋抽查標準」）、
錯字（「混擬土」）與全國法規資料庫沒有的行政規則（「加強公共工程職業安全衛生管理作業要點」）。

### 產生範例文件

```bash
.venv/Scripts/python scripts/generate_samples.py
```

會在 `data/samples/` 產生 `sample_quality_plan.docx` 與 `.txt`，內容涵蓋六種比對結果；
另有同一份內容的掃描版 `sample_quality_plan_scanned.pdf`（只有點陣圖，用來驗收 OCR）。

---

## 使用流程

1. **上傳**：選擇 `.docx` / `.pdf` / `.txt`（預設上限 50MB）。系統以 SHA-256 去重，重複檔案會回 409。
2. **開始分析**：建立一筆背景任務，畫面即時顯示進度（解析 → 抽取 → 正規化 → 比對 → 查詢）。
3. **檢視清單**：依狀態、覆核狀態、信心分數篩選。需要人工留意的項目會標色。
4. **逐筆檢視**：點任一列打開詳細面板，可看到原始段落、抽取方式、比對理由、外部查詢紀錄與 AI 使用情形。
5. **人工覆核**：標記「確認正確」或「判定錯誤」。覆核狀態與系統判斷各自獨立記錄，覆核不會蓋掉系統結果。
6. **匯出報告**：Excel / CSV / PDF。

### 總覽、稽核紀錄與法規異動監控

- **總覽**：文件數、引用狀態分布、待處理引用（需要人工確認且還沒覆核）、比對到假資料的筆數、
  待處理最多的文件、最常引用的法規。點文件直接打開它的分析畫面。
- **稽核紀錄**（租戶管理員）：誰在何時上傳、分析、覆核、匯出、管理帳號，以及每一次登入失敗。
- **法規異動監控**：對文件引用到的法規重新查詢來源，比對狀態與修正日期。偵測到變動會更新法規主檔、
  列出受影響的文件，但**不會自動改掉引用的狀態**——由人看過後重新分析。管理員可在總覽按「立即檢查」，
  或用排程在同步官方資料後跑：

```bash
python scripts/sync_taiwan_law.py && python scripts/sync_catalogs.py; python scripts/check_regulation_changes.py
```

有新異動時腳本以結束碼 2 結束，排程可據此判斷是否有新異動（`sync_catalogs` 也一樣，所以它後面接分號）。

`scripts/sync_catalogs.py` 同步**行政規則與地方法規目錄**（`data/admin_rules.json`）和**標準目錄**（`data/demo_standards.json`）：
依每筆的官方網址（`source_url`）重讀工程會法規資料庫、勞動部法規資料庫、新北市法規查詢系統與標準檢驗局 CNS 網路服務系統，
更新狀態（廢止）、公發布與修正日期、標準版次；更名的把舊名留成別名，每筆記下 `synced_at`。讀不出必要欄位就不改那一筆、
列出原因；`--dry-run` 只列出會變什麼。ISO、ASTM、BSI 官網擋自動讀取，那幾筆和日期抄自 PDF 的一筆列為「需人工查證」。
2026-11 實測：13 部行政規則同步 11 部、11 部標準同步 6 部，結果和人工查證一致。

**每週自動排程（Windows）**：`scripts/scheduled_sync.ps1` 依序跑上面三步（全國法規同步失敗就不跑後兩步），
紀錄寫在 `data/logs/`（已 gitignore）。`scripts/register_scheduled_sync.ps1` 把它註冊成工作排程器的工作
「EngineeringQuality-RegulationSync」，預設每週一 09:00，以目前登入的使用者、只在登入時執行（不儲存密碼），
錯過的排程開機後補跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1                      # 註冊（每週一 09:00）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1 -Day Friday -At 17:00 # 改時間
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_scheduled_sync.ps1 -Remove              # 移除
```

目錄同步會改 repo 裡的 `data/admin_rules.json`、`data/demo_standards.json`（狀態、日期與 `synced_at`），有變動要記得提交。
Linux／macOS 用 cron 跑同一串指令即可。

### 示範功能（以假資料驗證）

下列功能需要真實資料或外部服務才能真正驗收；在那之前，都附了假資料讓整條流程跑得起來。
每一項的畫面或紀錄都會標明「示範」，不會讓人以為是真的。

| 功能 | 怎麼試 | 假在哪裡 |
|---|---|---|
| **AI 輔助**（沒有 API key 時） | `.env` 設 `ENABLE_LLM_FALLBACK=true`、`LLM_PROVIDER=demo` | 固定規則，不是模型；紀錄的模型名稱是「demo-rules（示範，非真實 AI）」 |
| **標準版次與廢止** | `REGULATION_SOURCES` 加上 `standards_demo`（排在 `mock` 前面） | 目錄只有 11 部（2026-11 依官方網站查證）；引用 `CNS 3090:2015` 會因「最新為 2025 年版」判為已修正，目錄外的標準仍是疑似對應 |
| **檢核表：契約圖與工法欄**（階段 2、4） | 把 `data/samples/project_demo/` 的四份文件掛到同一個專案（標單／施工規範／契約圖／其他），建立工項與檢核表 | 契約圖是文字示意的 PDF。另有秀山分隊的示範契約圖 `data/samples/xiushan_contract_drawings_demo.pdf`（33 張，`scripts/generate_xiushan_drawings_demo.py` 產生）：圖目錄是假的，但版面照真實 CAD 圖，讀取走真實圖的同一條路 |
| **跨文件搜尋**（Phase 2 RAG 的替身） | 上方「搜尋」分頁 | 字詞相似度，不是語意模型；換個說法可能找不到 |

### 完整示範專案（一個專案看完所有功能）

`data/samples/full_demo/` 的七份文件（`scripts/generate_full_demo.py` 產生，全部是假資料，每份都印「示範（假資料）」）：
標單、施工規範（13 章，含機電測試小節）、Word 契約書（條號寫在段落裡）、需求書、CAD 版面的建築結構圖（含圖號索引表）、
**掃描版面的水電圖**（整頁圖片，要 OCR）、整體品質計畫（三張品質管理標準表，故意漏寫幾個規範值）。

```bash
python scripts/generate_full_demo.py
python scripts/seed_full_demo.py --username <帳號> --password <密碼>   # 後端要先跑起來；也可用 DEMO_USERNAME / DEMO_PASSWORD
```

seed 會匯入示範企業內部文件清單、上傳七份文件並設定角色、逐份分析規範與契約的法規引用（SQLite 一次只能一個寫入者，
所以不並行）、建立工項與檢核表。建議用獨立的示範資料庫跑，不要混進正式資料：`.claude/launch.json` 的 `backend-demo`
把 `DATABASE_URL` 指到 `data/demo_showcase.db`（已 gitignore），並啟用 `standards_demo`。看得到的結果：

| 功能 | 示範專案裡的例子 |
|---|---|
| 工法選定／未定 | 模板：需求書指定系統模板（OK）；鋼筋：規範列搭接／續接器／銲接、契約沒指定（請檢討使用何種工法） |
| 標單有、契約圖沒有 | 預拌混凝土沒有任何圖名提到混凝土 |
| 契約圖有、標單沒有 | A8-01 景觀植栽配置圖 |
| 掃描契約圖 OCR | 水電圖四張讀出圖名（標「OCR」），兩張圖號讀不到寫「第N頁」；開關箱（KW-MP PANEL）對到 E-01 電氣單線圖 |
| 契約欄引條號 | 鋼筋：「第11條 履約品管」「第11條 履約品管／品質計畫」 |
| 法規雙重規範提醒 | 女兒牆、樓梯扶手、防火門、昇降機、透水鋪面、綠建材六條都觸發 |
| 功能運轉檢測初稿 | 昇降機、給水、配電盤取自規範測試小節；無熔線斷路器規範沒寫測試，用通用範本 |
| 品質計畫審查 | 鋼筋表漏 40D、±6mm；混凝土表漏 CNS 1232；假設工程表本案規範沒有對應的章 |
| 依據查證 | CNS 560／3090／1232 由標準目錄查證、無障礙設施設計規範由行政規則目錄查證；「測量法」查無此法規（真實名稱是測繪法，示範文件故意寫錯） |
| 專案文件 | 專案頁列出已掛的七份文件與角色 |

`backend/tests/api/test_full_demo.py` 鎖住上面的結果（掃描水電圖那一項要 Tesseract 繁中語言資料才跑）。

**檢核表示範專案的預期結果**（`scripts/generate_project_demo.py` 產生）：

| 工項 | 結果 | 原因 |
|---|---|---|
| 普通模板 | OK | 相關圖 S-02；規範列出鋼模／木模／系統模板，需求書指定系統模板 |
| 鋼筋 | 請檢討使用何種工法 | 相關圖 S-03；規範列出搭接／續接器／銲接，契約文件沒指定 |
| 預拌混凝土 | 標單有，契約圖沒有 | 沒有任何圖名提到混凝土 |
| 施工測量、安全衛生 | 不判斷契約圖 | 01 類一般要求本來就不畫在圖上 |
| A-08 景觀植栽配置圖、S-01 結構平面圖 | 契約圖有、標單沒有 | 圖名對不到任何工項（專案層級，列在檢核表上方） |

重新分析（文件頁的按鈕，或法規異動的「重新分析受影響文件」）時，同一段落裡同一筆引用如果狀態沒變，
保留原本的人工覆核；狀態變了的回到未覆核，比對理由會寫出變化與原本的覆核者。

### 檢核表的契約欄、契約圖與品質管理標準表初稿

- **契約欄**：每個工項列出契約書提到它（或它所屬分項）的地方，最多三處，寫**頁碼與前面最近的小標題**
  （「p17 假設工程之組立及拆除」）。秀山契約書的條號是 Word 自動編號、PDF 文字層沒有，所以不推算條號。
  契約是 Word 檔、段落本身寫著「第11條　履約品管」時（另案的工程會統包契約範本），出處寫到條：
  「第11條 履約品管／3.金屬材料」（25 條都抓得到；Word 沒有頁碼，所以不寫頁）。
  這只是「契約提到這裡」，不影響檢核結果。秀山 1028 個工項有 54 個找得到。
- **契約圖可以分好幾冊**（建築、結構、水電），每一冊都讀。工項除了用自己的名稱，也用所屬**分項**的名稱
  （「開關箱設備工程」）對圖名——計價工項「KW-MP PANEL」對不到圖，分項對得到「開關箱單線圖」。
  分項是「直接工程費」往下兩層以內更細的群組；工種那一層（「水電工程」）太粗，不用。
- **掃描的契約圖**（用印後掃描、沒有文字層）改用 OCR 讀每一頁右側標題欄的圖名與圖號，結果標示「OCR」；
  圖號讀不到時寫「第N頁」。OCR 一頁約 2 秒，同一冊只讀一次，之後重建檢核表沿用。需要 Tesseract 繁中語言資料。
  圖號不是一頁一頁各自決定：每頁的圖號格（只框值、擦掉框線）讀兩三次當候選，同一冊的**掃描圖號索引表**
  讀成白名單，整冊一起投票、檢查編號順序、補上夾在中間的頁（`scanned_sheet_index`，規則寫在模組說明裡）。
  選用 `TESSDATA_BEST_PATH`（tessdata_best 的 chi_tra、chi_tra_vert、eng）：fast 模型讀不出像圖名的頁再用 best 模型補讀。
  同一冊有文字層的**圖號索引表**時，OCR 讀到圖號的頁改用索引表的圖名（沒有錯字），圖名讀不出來的頁照索引表列出。
- **品質管理標準表初稿**（橘框表單的第一種）：檢核表「章節」欄的「標準表初稿」下載那一章的 Excel，
  欄位照整體品質計畫的品質管理標準表（施工流程｜管理項目｜管理標準｜檢查時機｜檢查方法｜檢查頻率｜
  不合格之處理｜管理紀錄｜備註）。內容取自本案施工規範那一章「2. 產品」「3. 施工」裡寫得出可檢查標準的句子，
  每一列註明出處（第03210章 3.4.1）；規範沒寫的檢查頻率留「（待填）」。**這是初稿**，要品管人員依圖說補正。
- **自主檢查表初稿**（承攬廠商）與**監造抽查標準表初稿**（監造單位：施工抽查標準表＋材料抽驗標準表）：同樣在
  「章節」欄下載，**由同一章的品質管理標準表初稿衍生**，三張表的檢查項目與標準一致。自主檢查表照整體品質計畫第七章
  的格式（檢查項目｜設計圖說、規範之檢查標準｜實際檢查情形｜檢查結果，分施工前／中／後），現場欄位留白。
- **施工要領初稿**（Word）：照整體品質計畫的施工要領結構——施工機具（留待填）、使用材料（標單裡計價代碼屬於這一章的
  工項）、施工方法步驟（規範「3. 施工」各小節的條文，「工程司」改為「監造單位」，同名小節合併）與施工流程圖
  （小節是檢驗、試驗、許可差，或條文要求檢驗、試驗、檢查認可的，標★檢驗停留點）。
- **功能運轉檢測初稿**（機電章才有，11／13／14／15／16 開頭）：設備功能運轉檢測標準表（承攬廠商）與測試抽驗標準表
  （監造）兩張工作表，欄位照整體品質計畫第六章。來源是規範「3. 施工」的測試、試驗、試運轉、檢驗小節；秀山規範多是
  沒改過的綱要範本、只列測試項目（「3.2.1 絕緣試驗」），這種照列項目、判定值寫「（規範只列項目，判定值待填）」。
  原本漏抓的三種寫法已修正（「3.3m」蓋掉 3.3 節標題、標題後接冒號與句子、沒有句號的檢驗條文）；整章沒有測試小節的
  （管材、衛生器具、斷路器…）用 `data/function_test_templates.json` 的通用測試項目，備註標「通用範本」。
  秀山 35 個機電章：27 → 35 章產生得出列。
- **品質計畫審查（橘框對綠框）**：把承攬廠商的整體品質計畫（.docx）掛成「品質計畫」，檢核表上方下載 Excel：
  計畫裡每張品質管理標準表對到本案規範哪一章、規範那一章有可比對值的條文（CNS 560、±6mm、25D、48 小時…）
  哪些在計畫那張表裡一次都沒出現。**只判斷「規範有、計畫沒寫」**；寫了但值不同、沒有可比對值的條文不判斷。
  秀山實測：7 張表裡 4 張對得到規範章（開挖及土方、兩張鋼筋、混凝土），總表、假設工程、基樁三張規範沒有對應的章。
- **法規雙重規範提醒**：同一個構件要同時滿足兩部以上規定的情形（邏輯圖的例子：頂樓 RC 欄杆要 1.1m，
  超過 1.5m 會被納入樓高）。目錄在 `data/cross_rules.json`，本案標單工項或契約圖圖名出現觸發詞就在檢核表上方提醒，
  並引出是哪幾項觸發的。6 條的條號與數值 2026-11 依全國法規資料庫（建築技術規則設計施工編第1、38、76、305、321條）
  與本案無障礙規範（205.2、207、305.2、406）查證；建築設備編條號、地方雨水貯留規定未查證，各條 provenance 寫明。
  只是提醒，不影響檢核結果。
  秀山標單 6 條都觸發（電梯 13 項、透水／雨水 21 項…）。
- **整體品質計畫初稿、監造計畫初稿**（Word）：檢核表上方下載。章節照秀山整體品質計畫的目錄（計畫範圍、權責分工、
  品管組織、施工要領、品質管理標準、材料及施工檢驗程序、設備功能運轉檢測、自主檢查表、不合格品管制、矯正預防與稽核）；
  監造計畫照監造的對應章節（材料設備抽驗、施工抽查、設備功能運轉測試抽驗…）。**標單用到的每一章規範**都產生施工要領、
  標準表、檢查表，內容和單獨下載的各張初稿相同；組織、權責、程序這些要公司與工地提供的章寫「（待填）」並說明要填什麼。
  秀山實測：標單用到 31 章，整體品質計畫初稿 83 張表、監造計畫初稿 57 張表，產生約 4 秒。
- **示範補正**（展示用）：檢核表上方勾選「示範補正」後，所有初稿與計畫的下載都把「（待填）」用示範內容補齊
  （`data/demo_fill.json`：依施工階段的檢查頻率、依章別的施工機具、範本測試項目的示範判定值、組織與程序章節的示範文字），
  每個補上的值標「（示範）」、段落以「【示範】」開頭，不寫真實人名；API 是各下載網址加 `?demo=true`。
  不勾選時輸出完全不變。秀山實測：兩份計畫補正後沒有任何「（待填）」。**示範內容不是本案實際資料，不可提送。**
- **承攬廠商品質管理程序範本**：整體品質計畫初稿的權責分工、材料及施工檢驗程序、自主檢查、不合格品管制，與監造計畫初稿的
  材料設備抽驗、施工抽查程序，先用同一營造廠在另案服務建議書寫的程序補上（`data/contractor_procedures.json`，
  公司名稱改成角色），每段標「【承攬廠商範本】」。另取建議書 3.1.2、3.1.3、3.1.14 補上品管組織與簽署責任、協力廠商參加的
  每日／每周／每月會議、PDCA 矯正預防，以及設備功能運轉後的操作維護訓練與點交（品質計畫第七章、監造計畫第六章）。
  範本沒涵蓋的（各協力廠商工作範圍、品管人員名單、內部稽核頻率與文件保存期限）仍留「（待填）」，
  勾「示範補正」才補示範文字。**範本是別案的程序，提送前要改成本案的。**

---

## 法規狀態的意義

系統刻意不做「有效 / 無效」二元判斷，因為工程文件裡的引用經常是簡稱、舊名、寫錯字或根本查無此規範。

| 狀態 | 意義 |
|---|---|
| `ACTIVE` | 現行有效 |
| `AMENDED` | 已修正，仍有效但版本已變動 |
| `REPEALED` | 已廢止 |
| `NOT_FOUND` | 查無此法規／標準 |
| `POSSIBLE_MATCH` | 找到疑似對應但無法確認，需人工確認 |
| `UNKNOWN` | 查詢失敗或尚未查詢 |

信心分數未達 `MATCH_AUTO_THRESHOLD`（預設 90%）的項目，畫面與報告會標示「疑似」。

**CNS / ISO / ASTM / JIS 等標準一律是 `POSSIBLE_MATCH`**，即使名稱完全命中也一樣。
這些多半是付費標準，公開來源通常只查得到「標準存在」，查不到最新版號，
所以系統不會承諾能自動判斷它們的有效性——這是架構限制，不是待修的缺陷。

---

## 目錄結構

```text
backend/app/
├── api/            HTTP 層：路由、參數解析、組裝 response（不含業務邏輯）
├── schemas/        Pydantic request/response 模型
├── models/         SQLAlchemy ORM 定義
├── repositories/   純資料存取（CRUD 與查詢組合）
├── services/       業務邏輯編排，唯一可以跨多個 repository 做事的層
├── parsers/        DOCX / PDF / TXT 解析
├── extractors/     抽取管線：Rule -> Dictionary -> (可選) LLM fallback
├── matching/       正規化引擎 + 比對引擎
├── sources/        法規資料來源 adapter（taiwan_law 官方 / mock 假資料）
├── ai/             LLMProvider 介面、Anthropic 實作、prompt 管理
├── jobs/           JobRunner 介面 + BackgroundTasks 實作
├── reports/        Excel / CSV / PDF 匯出
├── core/           設定、資料庫、log、錯誤、上傳驗證
└── main.py

frontend/src/       React + Vite + TypeScript（無 UI 框架，純 CSS）
data/               別名字典、假資料、官方法規索引（產生的，不進版控）
migrations/         Alembic
scripts/            sync_taiwan_law.py、seed_data.py、generate_samples.py
docker/             Dockerfile 與 nginx 設定
```

資料流：

```text
上傳檔案 → parsers → document_sections
        → extractors（規則 + 字典 + 可選 LLM）→ 候選
        → matching/normalizer → 正規化名稱
        → services/matching_service → sources adapter 查詢 → regulations
        → matching/matching_engine → 狀態 + 信心 + 比對理由
        → regulation_references（結果）
        → services/report_service → reports/ → 檔案
```

---

## 常見修改該動哪裡

| 想做的事 | 改哪裡 |
|---|---|
| 抽不到某種法規名稱 | `backend/app/extractors/rule_engine.py` 的三張表（先在 `data/golden_set/` 補標註） |
| 想知道抽取準不準 | `pytest backend/tests/golden -s` |
| 某個簡稱沒有對到正確法規 | `data/alias_dictionary.json` 加別名，重跑 `scripts/seed_data.py` |
| 調整比對寬鬆程度 | `.env` 的 `MATCH_AUTO_THRESHOLD` / `MATCH_POSSIBLE_THRESHOLD` |
| 更新官方法規資料 | 重跑 `python scripts/sync_taiwan_law.py`（官方每週更新一次） |
| 更新施工綱要規範目錄 | 重跑 `python scripts/sync_pcces.py` |
| 再接其他法規來源（CNS、企業內規） | 新增 `backend/app/sources/xxx_source.py`，在 `sources/__init__.py` 註冊，改 `REGULATION_SOURCES` |
| 換 AI 供應商 | 新增 `backend/app/ai/xxx_provider.py`，在 `ai/factory.py` 註冊，改 `LLM_PROVIDER` |
| 換背景任務引擎（Celery） | 新增 `backend/app/jobs/celery_runner.py`，改 `api/deps.py` 的 `get_job_service` |
| 報告要加欄位 | `backend/app/reports/columns.py`（三種格式共用） |
| 新增匯出格式 | 新增 `backend/app/reports/xxx_report.py`，在 `reports/__init__.py` 的 `EXPORTERS` 加一行 |
| 改前端顯示文字 | `frontend/src/labels.ts` |
| 匯入企業內部文件清單 | 「總覽」→「企業內部文件」，或 `scripts/import_enterprise_documents.py` |
| 改企業內部文件清單的欄位或選項 | `backend/app/services/enterprise_document_service.py`（匯入檢查），再跑 `scripts/generate_enterprise_template.py` 重產範本 |
| 改「來源未就緒」的警告文案 | `frontend/src/labels.ts` 的 `SOURCE_WARNINGS` |
| 新來源要回報就緒狀態 | 在該 adapter 覆寫 `readiness()`（見 `sources/base.py`） |

---

## AI 的角色與界線

AI 是輔助，不是真相來源。

**會用到 AI 的地方（都可以關掉）**

- 規則與字典都抽不到東西時，把該段落交給 LLM 做 fallback 抽取。
- 字串相似度落在 70%–90% 的模糊區間時，請 LLM 給輔助判斷。它只能微調分數與補充理由，最多把分數推到自動門檻邊緣，主導權仍在規則引擎。
- 把已經算好的統計結果改寫成人類可讀的摘要（只負責語言表達）。

**AI 絕對不會做的事**

- 決定法規是否有效／已廢止／已修正 — 只能來自 `sources/` adapter 回傳的資料或人工覆核。
- 直接寫入 `regulations.status`。

每一次呼叫都會寫入 `ai_invocation_log`（模型、prompt 版本、輸入、輸出 JSON、信心、耗時），可回溯任何一筆判斷。
送進 LLM 的文件內容一律視為不可信輸入，包在 `<document_content>` 標籤裡，並要求 structured output 再用 Pydantic 驗證；驗證失敗就丟棄該次結果，不重試。

**完全關閉 AI**：`.env` 設 `ENABLE_LLM_FALLBACK=false`（或不填 `ANTHROPIC_API_KEY`）。
系統仍可完整跑完整條流程，只是抽取召回率與比對信心會下降。

**沒有 API key 但想看 AI 流程**：設 `LLM_PROVIDER=demo`。它用固定規則代替模型（抽取幾種內部文件
字尾、用字元重疊度判斷名稱相似、把統計結果排成摘要），紀錄照樣寫進 `ai_invocation_log`，模型名稱
標明「非真實 AI」。**不能用它的結果評估 AI 的效果。**

---

## 測試

```bash
.venv/Scripts/python -m pytest
```

- `backend/tests/unit/` — 抽取、正規化、比對、解析、上傳驗證、log
- `backend/tests/integration/` — DOCX → 解析 → 抽取 → 比對 → 資料庫的完整鏈路，以及報告與匯出
- `backend/tests/api/` — 走完 upload → analyze → 輪詢 → references → review → report
- `backend/tests/golden/` — 抽取準確度的回歸閘門（見下）

測試使用獨立的 SQLite 檔案並關閉 AI，不會動到開發用資料庫。

### 抽取準確度

```bash
.venv/Scripts/python -m pytest backend/tests/golden -s
```

會印出逐案例的漏抽／亂抽清單與 recall / precision，並擋住退步（門檻寫在
`backend/tests/golden/test_extraction_accuracy.py`，只能往上調）。

**這是調整抽取行為的唯一依據。** 要補別名字典或改 `rule_engine.py` 的黑名單之前，
先在 `data/golden_set/` 補標註，否則不會知道修好一個案例的同時弄壞了幾個。
標註格式與匿名化規則見 `data/golden_set/README.md`。

前端（vitest + Testing Library，jsdom 環境，不需要後端）：

```bash
npm test --prefix frontend
```

- `frontend/src/**/*.test.tsx` — 元件行為與 App 串接（用假的 `fetch` 回應驅動）

---

## 設定

所有設定集中在 `backend/app/core/config.py`，實際值由環境變數或 `.env` 提供。
完整清單與說明見 [`.env.example`](../.env.example)。比較常調整的：

| 變數 | 預設 | 說明 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL | 本機可改成 `sqlite+aiosqlite:///./data/app.db` |
| `MAX_UPLOAD_SIZE_MB` | 50 | 改這個也要同步改 `docker/nginx.conf` 的 `client_max_body_size` |
| `MATCH_AUTO_THRESHOLD` | 0.90 | 高於此值直接採用法規狀態 |
| `MATCH_POSSIBLE_THRESHOLD` | 0.70 | 低於此值判定為 `NOT_FOUND` |
| `ENABLE_LLM_FALLBACK` | true | 設 false 可完全關閉 AI |
| `REGULATION_SOURCES` | `mock` | 逗號分隔，**順序即優先順序**；接官方資料設 `taiwan_law` |
| `TAIWAN_LAW_INDEX_PATH` | `data/taiwan_law_index.json` | 官方法規索引位置（不要設成空字串） |
| `PCCES_INDEX_PATH` | `data/pcces_index.json` | 施工綱要規範目錄位置 |
| `REGULATION_CACHE_TTL_DAYS` | 7 | 幾天內的法規資料視為新鮮，不重複查外部來源（僅適用於已由最優先來源寫入的資料） |
| `PDF_FONT_PATH` | 空 | PDF 匯出的中文字型；留空會自動搜尋常見系統字型 |
| `ENABLE_OCR` | true | 掃描版 PDF 的 OCR；設 false 則掃描檔會報錯 |
| `OCR_LANGUAGES` | `chi_tra+eng` | Tesseract 語言代碼，用 `+` 連接 |
| `TESSDATA_PATH` | 空 | Tesseract 語言資料目錄；留空用 `TESSDATA_PREFIX` 或系統安裝位置 |
| `TESSDATA_BEST_PATH` | 空 | 選用：tessdata_best 目錄。掃描契約圖讀不出圖名的頁用它補讀（較慢）；留空不補讀 |

---

## 目前的限制

- **官方資料庫只涵蓋「法律」與「法規命令」**。實際查證過，以下都**不在** `taiwan_law` 範圍內，會落在 `NOT_FOUND`，需要其他來源補或人工查證：
  行政規則與作業要點（如「公共工程施工品質管理作業要點」）、工程規範（如「結構混凝土施工規範」）、CNS/ISO/ASTM/JIS 標準。
- **`pcces` 只涵蓋工程會的「共通性工項施工綱要規範」**。各機關自訂的規範（「混凝土結構施工規範」是內政部的）與作業要點都不在裡面。
  而且它**刻意不做模糊比對**：章名是工項/材料名（「卜特蘭水泥」「鋼筋」「品質管理」），實測會和帶編號的標準引用撞到 0.90 以上並被自動採信。
  因此只有引用帶章碼、或字面寫了「綱要規範」時它才回答，其餘一律回空。細節見 `backend/app/sources/pcces_source.py` 的模組說明。
- **`pcces` 用的不是工程會公告的 Open API**。公告的那支（`pcic.pcc.gov.tw/pwc-web/service/api001`）只有「取得 Token」與「決標價格之 XML 驗證」，沒有法規資料。
  這裡用的是技術雲下載頁背後的 endpoint，無需認證但沒有文件，可能無預警改。改掉時同步會失敗、前端會顯示來源未就緒，不會安靜地給錯答案。
- **官方資料庫不保留已更名法規的舊名**。例如「勞工安全衛生法」已更名為「職業安全衛生法」，
  舊名在官方資料庫查不到，只會模糊比對到新法並標示為「疑似對應」。舊名對應要靠 `data/alias_dictionary.json` 自行維護。
- **法規資料是同步下來的快照**，不是即時查詢。官方大約每週更新，重跑 `scripts/sync_taiwan_law.py` 即可。
- **掃描版 PDF 靠 OCR，會有錯字**：辨識結果有標示但不會自動校正，表格與小字特別容易漏。設計圖說的圖頁也會送 OCR，但尺寸標註這類圖內文字多半讀不完整，仍會標示「以圖為主」。
- **DOCX 沒有頁碼**：頁碼由 Word 排版決定，解析階段取不到，因此一律顯示「—」而不是猜一個數字。PDF 有頁碼。
- **未實作 NER 抽取層**：MVP 只有規則 + 字典 + LLM fallback；要加 NER 只需在 `extractors/` 多插一層，候選格式不變。
- **帳號登入**：使用本機帳密與租戶隔離；部署前先執行 `scripts/bootstrap_admin.py` 建立第一位管理員。未提供公開註冊或密碼重設郵件。
- **向量資料庫未啟用**：Phase 2 才會加入（`docker-compose.yml` 裡已預留註解）。目前的「搜尋」是字詞相似度的示範版，不是語意搜尋。
- **檢核表階段 2、4：契約圖只讀標題欄的圖號與圖名**（讀不懂圖面）。CAD 匯出的圖（某宿舍統包工程竣工圖，331 頁）
  靠文字位置讀到 328 張。同案的結構竣工圖（54 頁）圖號與 S0、S1 頁的圖名是**寬度 0 的淡灰髮絲線**、不在文字層：
  算圖時把最細線寬加粗再 OCR 標題欄那兩格，讀到 44 張（22 張靠 OCR）；再加上 best 模型補讀與圖號索引表校正，
  49 張（27 張圖號靠 OCR，標示「OCR」；圖名都是索引表的正確寫法）。目錄頁與圖號、圖名都讀不出來的頁不列，
  圖面註解句（「2. 為使…」「…的範圍。」）不當圖名。整冊約 25 秒。秀山的真實契約圖是**用印後掃描**（建築 137 頁、結構 32 頁、水電 117 頁），改用 OCR 讀標題欄：
  圖名約八成讀得到但有雜字，簽名靠「同頁事務所欄出現的字」去除，仍有少數讀錯字的殘留。三冊 OCR 約 11 分鐘（fast 模型），同一冊只讀一次。
  **圖號（2026-11 改善）**：

  | 冊 | 改善前 | 改善後 | 核對 |
  |---|---|---|---|
  | 結構圖 32 頁 | 12（其中 6 頁讀錯：S2-01→S7-01、S2-02→S9-02…） | 32 | 對索引表逐頁核對，32 頁全對 |
  | 建築圖 137 頁 | 44（含 AS5-02、NI0-17 這類讀錯） | 131 | 編號連續；靠補頁、索引表外讀法的頁抽樣看圖，全對 |
  | 水電圖 117 頁 | 44 | 99 | 同上（ES、AC 兩段索引表沒讀到，靠每頁兩次讀法一致） |

  三冊合計 100 → 262 頁（35% → 92%）。做法：「DWG NO.」標籤常讀成「OWG」「DWC」「WG」，原本有 70 頁連標籤都找不到；
  圖號格原本連「圖號 DWG NO.」標籤與框線一起辨識，改成只框值那一格、先擦掉框線（Tesseract 會把框線當成字的一部分），
  再用三冊各自的掃描索引表當白名單整冊投票。讀不到的頁仍寫「第N頁」：多半是圖號格被印章蓋到，
  或水電圖消防（F）那一段索引表與標題欄都讀不清楚。索引表 OCR 漏讀幾張時，前後兩張流水號差剛好等於頁數差的照流水號補；
  前後同字首、中間夾一張別的字首的（建築圖第 39 頁讀成同冊附的水電索引上的「S-01」）先丟掉再補。
  **圖名也從索引表來**：每個圖號右邊那一格用中文模型讀三種解析度，和標題欄讀到的圖名逐字投票，每個字至少兩票一致、
  結果像圖名才用（`scanned_sheet_index.best_title`）。列得出來的圖 204 → 221 張（結構 20 → 28、建築 95 → 100、水電 89 → 93），
  另有錯字被糾正（「外并配筋圖一」→「外牆配筋圖一」、「電氣單線圖ARS)」→「電氣單線圖.負載表(3)」）。建築圖索引表字小、
  多欄排版，讀出來多半各亂各的，幾乎都沿用標題欄的圖名。
  工法用秀山的真實規範校正：只讀各章「3. 施工」節，認「下列…之一」接方括號、講做法的「[A]或[B]」、
  「續接應依下列規定辦理 (1)搭接 (2)銲接…」三種寫法。整本規範只有鋼筋續接一組選項。
- **契約圖改以分項比對**：計價工項名稱（「KW-MP PANEL」）對不到圖名，改用工項或所屬分項的名稱對。
  秀山實測「標單有，契約圖沒有」：示範圖逐項比對 750 筆 → 真實掃描圖分項比對 595 筆 → 開關箱對單線圖後 312 筆 → 加上 best 模型補讀 297 筆；fast 模型下，圖號整冊決定後 290 筆 → 圖名也從掃描索引表來之後 279 筆 → 圖名拆主體、用標單用詞校正錯字後 117 筆 → 粉刷貼磚對飾材配置圖、消防設備對消防圖後 60 筆 → 接地避雷對避雷圖後 44 筆 → 天線對電視設備圖、防火填塞材料對防火阻絕圖、輕隔間對輕隔間詳圖後 **30 筆**。
  279 筆裡大多不是錯字，而是圖名把樓層寫在前面、真正畫的東西寫在括號或後段：「一層平面圖(排水配置)」「二層配置圖電信,資訊網路及電視設備」。舊規則看圖名主體的開頭兩字（「一層」），永遠對不到「污排水PVC管」「資訊網路系統」。現在另外把圖名拆成幾段（`drawing_reader.title_subjects`：去樓層方位前綴、去圖種字、依分隔符拆開），某一段**整段**出現在工項或分項名稱（括號附註不算）就算相關。OCR 錯字用本案標單的用詞校正（`title_vocabulary`，只用在比對、不改存下來的圖名）：「影視對讚」→「影視對講」才對得到監控系統分項。
  裝修工程的水泥漆、壁磚、踢腳、粉光畫在「地坪及牆面飾材配置圖」「天花飾材配置圖」上，消防圖叫「消防設備平面圖」，
  標單分項叫「滅火器及火警自動警報設備」——兩邊沒有共同的字，比照開關箱對單線圖，加進 `drawing_reader.SHOWN_ON`。
  水電圖消防那一段（F0-01～F1-06）的標題欄，OCR 把「DWG NO.」和圖號讀成同一行，原本框圖號格框到空白；
  現在那一行讀到的圖號也算一票（水電圖圖號 95 → 99 頁）。各段的索引頁是該段第一張（某字首第一次出現、流水號 01），
  圖名讀不出「索引」也會試讀。消防那一段的圖名是空心細字，加粗筆畫後 OCR 仍不穩定，沒有採用。
  接地避雷設備工程（含底下的裸銅線、PVC 電線、PVC-E 管小分項）的圖叫「…(避雷針配置)」「電避雷針詳圖」，
  分項名稱沒有完整的「避雷針」：避雷、接地、雷擊 → 圖名有「避雷」的圖。
  剩下的 30 筆逐筆對過圖名：24 筆可能畫在圖上但圖名沒寫（發電機房進排風 7、車位畫線與防撞條 6、電纜線架 5、
  窗簾盒門檻拉門明鏡 5、層間接縫防水 1），要人工翻圖；6 筆本來就不畫（告示牌、勘檢作業費、裝配工資、五金另料）。
  比較寬鬆的配對：樓梯磁磚、樓梯間標示牌對到「牆、樓梯及其他配筋詳圖」（同一個位置，但不是那一項的圖）。門窗、金屬、給排水等分項
  全部對得到。開關箱設備（315 項）原本幾乎都對不到——不是 OCR 讀亂，而是水電圖**沒有一張叫開關箱**：
  開關箱、配電盤畫在電氣單線圖與負載表上。現在開關箱類工項對「單線圖」「負載表」（`drawing_reader.SHOWN_ON`），
  315 項全部對得到（只算水電圖：對得到的工項 204 → 518）。只有「直接工程費」底下的工項才比對。
  水電圖 OCR：fast 繁中模型 117 頁讀到 89 頁的圖名、35 頁的圖號；加上 best 模型補讀後 108 頁、43 頁（約 216 → 533 秒）。
  仍有錯字（「平面圖」讀成「在面圖」）。簽名的 OCR 變體（同一名字讀成兩三種）從「完整圖名後面多出的三字」學出來拿掉。
  秀山的掃描冊沒有文字層的索引表，改讀掃描的索引表（見上）。加對比、二值化、放大都試過，標題欄圖名沒有穩定改善。
- **秀山真實文件的回歸測試**：`backend/tests/api/test_xiushan_checklist.py`，有 `工程文書/` 與 `data/pcces_index.json`
  時才跑。不掛契約圖時鎖住摘要：OK 239、本案規範未收錄 188、請確認依據 592、工法未定 9（共 1028），契約欄 54 項。
  三冊真實掃描圖的測試要 OCR 約 12 分鐘，設 `XIUSHAN_OCR=1` 才跑。
- **行政規則與地方法規目錄只有 13 部**：全國法規資料庫不收「要點」「綱要」與地方自治法規。`admin_rules` 列了秀山分隊文件實際引用的 13 部，
  2026-11 依工程會法規資料庫、新北市法規查詢系統等官方網站查證狀態與日期（每筆寫官方網址）。查證時發現：契約書寫的
  「營建混合物資源處理場設置管理要點」是新北市的要點、已於 2026-09-08 廢止；「栽培介質防範紅火蟻…要點」現行名稱多了
  「花卉與種苗及」；「加強公共工程職業安全衛生管理作業要點」只查到勞動部收錄的 2014 年版，是否現行未確認。
  目錄外的要點仍要人工查證；目錄內的由 `scripts/sync_catalogs.py` 自動同步（見「法規異動監控」）。
- **標準目錄只有 11 部**：`standards_demo` 2026-11 依標準檢驗局 CNS 網路服務系統、ISO、ASTM、BSI 查證（ISO、ASTM 官網擋自動讀取，
  依官方網域的搜尋結果）。查證時發現舊的示範資料把 CNS 4750 寫成已廢止的鋼筋標準，實際是現行的「鋼管施工架」；
  ISO 9001、ISO 14001 已有 2026 年版。CNS 六部由 `scripts/sync_catalogs.py` 自動同步，ISO／ASTM／BSI 要人工查證。
  目錄外的標準仍以 `mock` 的「疑似對應」為準。
