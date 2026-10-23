# 工程法規／規範智慧檢索與符合性檢查平台

上傳工程文件（DOCX / PDF / TXT），系統會抽出文件中引用的法規、標準與施工規範，
查詢它們目前的狀態，並清楚標示哪些項目需要人工確認，最後匯出可稽核的報告。

設計文件在 [`docs/`](docs/)：
[架構](docs/architecture.md)｜[資料庫](docs/database.md)｜[API](docs/api.md)｜[開發計畫](docs/development-plan.md)

## 法規資料來源

系統支援兩個來源，用 `REGULATION_SOURCES` 切換（逗號分隔，**順序即優先順序**）：

| 來源 | 內容 | 可信度 |
|---|---|---|
| `taiwan_law` | 法務部**全國法規資料庫** Open API：法律約 1,346 筆、法規命令約 10,447 筆 | 官方資料 |
| `pcces` | 工程會**公共工程施工綱要規範**目錄，315 章（含已刪除章節） | 官方資料 |
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
完整清單與說明見 [`.env.example`](.env.example)。比較常調整的：

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
- **向量資料庫未啟用**：Phase 2 才會加入（`docker-compose.yml` 裡已預留註解）。
