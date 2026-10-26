# 系統架構設計（Phase 0）

工程法規／規範智慧檢索與符合性檢查平台

版本：v0.1（Phase 0 架構確認稿）
狀態：Phase 0 架構紀錄；本機登入與租戶隔離已由 `docs/superpowers/specs/2026-10-21-local-auth-and-tenant-isolation-design.md` 補充並確認

---

## 0. 本文件範圍與前提

本文件是在你提供的完整需求書基礎上，加入架構師視角的檢視與調整。所有調整都會標示「為什麼調整」，未調整的部分維持你原本的設計。

已確認的四個前提（來自你的回覆）：

1. LLM Provider：第一版預設 **Anthropic Claude API**，但架構上以 `LLMProvider` 介面抽換，之後可換 OpenAI／Gemini／本地模型。
2. 官方法規資料來源：**尚無串接經驗**。本次嘗試透過 WebSearch／WebFetch 調研全國法規資料庫、data.gov.tw 等公開資料來源時，此環境的網路存取被 robots.txt／代理層擋下，**無法在本次 Phase 0 內完成即時查證**。因此 MVP 階段只交付 `MockRegulationSource` + 介面設計，真實資料來源串接（Phase 8）列為待辦，需要你日後提供官方 API／資料文件，或在有網路存取的環境重新調研後再實作，避免我自行捏造 API 規格（這也是你在需求書第三十二節明確要求的事）。
3. 部署環境：第一版只需要本機／單機 `docker compose up` 即可運行的開發環境。
4. 使用規模：單人或少數人使用、文件量不大 → 第一版用 **FastAPI BackgroundTasks**，不引入 Celery/Redis，但用抽象層包裝，未來可平移升級。

---

## 1. 我建議調整的地方（與你的原始設計比較）

在完全遵照你的規格之前，先列出我認為需要調整或補強的地方，逐項說明理由。這些調整都是「加東西 / 補洞」，沒有推翻你的核心設計。

### 1.1 新增 `jobs`（分析任務）資料表

你的需求書第十八節要求「上傳不應阻塞 HTTP request，要用背景任務」，但第十三節的資料表清單裡沒有一張表用來追蹤「這次分析跑到哪一步、有沒有失敗、進度多少」。前端要輪詢進度、要顯示「分析中 / 失敗原因」，都需要有一個獨立於 `documents` 的任務紀錄（一份文件未來可能被重新分析多次）。因此新增 `jobs` 表，這是能不能達成你在第三十八節「Definition of Done」裡「按下開始分析後系統自動完成整個流程」的必要條件。

### 1.2 新增 `ai_invocation_log`（AI 呼叫紀錄）表，與 `regulation_queries` 分開

你的需求書第二十四節要求「所有 AI 結果都要可追蹤：model / prompt_version / input / output / timestamp / confidence」。但第十三節裡唯一像日誌的表是 `regulation_queries`，它的設計目的是記錄「外部法規資料來源查詢」（source / query / result），語意上是給 `sources/` adapter 用的，不是給 `ai/` LLM 呼叫用的。如果硬塞在一起，未來要分別稽核「AI 有沒有亂猜」跟「政府 API 有沒有查到」會很難拆開。因此拆成兩張表，各司其職。

### 1.3 在 `regulation_references` 加入人工覆核欄位

你在第二十四節寫得很清楚：「不要做成 AI 說有效 → 系統直接判定有效」。但目前 schema 裡的 `status` 欄位如果只由系統寫入，介面上使用者看到的「狀態」其實無從分辨這是機器判斷還是人已經確認過。因此加入 `review_status`（`UNREVIEWED / CONFIRMED / REJECTED`）、`reviewed_by`、`reviewed_at`、`review_note` 四個欄位，讓「系統判斷」與「人工覆核」是兩個獨立且都可追溯的狀態，這也直接對應第十五節前端「詳細資訊」頁面應該要有的覆核操作。

### 1.4 核心資料表以 `tenant_id` 隔離

Migration `0006` 建立租戶表，將既有文件、專案和法規歸入預設租戶，並把根資源的 `tenant_id` 設為必填外鍵。登入 session 決定目前租戶；文件、專案與法規的讀寫都以該租戶範圍查詢，段落、工作、引用、章節、依據及報告則先沿所屬文件或專案驗證。文件雜湊改為租戶內唯一。

### 1.5 Matching Engine 明確設計成「規則優先、LLM 可關閉」

你在第十一節已經說 LLM 不是真相來源，我完全同意，並更進一步：**加入一個環境變數 `ENABLE_LLM_FALLBACK`，預設為 true，但可以整個關掉。** 原因是：不少工程顧問公司 / 得標廠商對於「文件內容是否可以送到外部 LLM API」有內規或資安要求。如果 Matching Engine 的核心比對邏輯（別名比對 + 字串相似度）在設計上就不依賴 LLM 才能動作，只把 LLM 當「候選不足時的加分項」，那麼即使關掉 LLM，系統仍然可以完整運作（只是信心分數/召回率會下降）。這對「未來產品化、賣給不同企業」這個目標很關鲜——不是所有客戶都願意讓文件內容出境。

### 1.5.1 型別守門：引用帶標準編號時，只採用標準型別的候選

比對引擎純粹比名稱相似度，沒有型別概念。接入公共工程施工綱要規範（`pcces`）時發現這會出事——該目錄存的是「工項／材料名」而不是文件名，用專案自己的比對器實測：

| 引用 | 最佳章節對應 | 分數 | 沒守門的話 |
|---|---|---|---|
| CNS 61 卜特蘭水泥 | 03052 卜特蘭水泥 | 0.90 | 自動採信 |
| CNS 560 鋼筋混凝土用鋼筋 | 03210 鋼筋 | 0.90 | 自動採信 |
| ISO 9001 品質管理系統－要求 | 01450 品質管理 | 0.90 | 自動採信 |
| 職業安全衛生法 | 01574 職業安全衛生 | 0.92 | 自動採信 |

把一份 CNS 標準判成一個施工綱要規範章節，是「**有信心的錯**」——比誠實回答查不到傷害大得多，而且查核報告一旦講錯話就不會再被信任。

因此 `MatchingEngine` 在評分之前先過濾候選：**引用本身帶標準編號（CNS / ISO / ASTM / JIS）時，只有 `STANDARD` 型別的候選有資格參賽**；一個都沒有就回 `NOT_FOUND`，並在理由裡寫明是型別不合而不是名稱不像。

刻意只在「文件裡真的出現標準編號」這個高精確度訊號上設限。抽取器猜的 `regulation_type` 會錯，拿它做通用的型別相容性檢查會製造大量假 `NOT_FOUND`。代價是資料庫裡型別標錯的標準會查不到——接受，這符合「不要給看似肯定但可能誤導的判斷」。

來源層另有第二道閘門（`PccesSource.search()` 只在有章碼或字面提到「綱要規範」時才回答）。兩層是刻意的：來源層是字串判斷，會有沒想到的寫法。

### 1.6 Background Job 用介面包一層，現在用 BackgroundTasks，之後可平移到 Celery

這是你自己在第十八節提出的升級路徑，我把它落實成一個明確的 `JobRunner` 介面（`run_analysis_job(document_id)` / `get_status(job_id)`），第一版的實作是 FastAPI `BackgroundTasks` + `jobs` 表輪詢，之後若要換 Celery/Redis，只需要換 `JobRunner` 的實作，`services/` 以上完全不用改。

### 1.7 前端技術選型：建議用輕量 React + Vite SPA，而非伺服器渲染模板

需求書沒有指定前端框架。我建議 React + Vite + TypeScript 的原因：這個系統的核心互動（法規清單表格、篩選、詳細面板、人工覆核、匯出）都是典型 SPA 場景，且你在第二十五、二十九節的長期規劃裡有 Dashboard、多專案、權限等更複雜的畫面，及早用 SPA 架構可以避免中途重寫。如果你更在意「越簡單越好、不想維護前端建置工具鏈」，另一個可行方案是 FastAPI + Jinja2 + htmx（幾乎不用寫 JS，但長期擴充性較弱）。**這點我先按 React+Vite 進行設計，如果你有不同偏好，這是少數幾個现在改動成本還很低的地方，可以隨時喊停。**

以上 7 點是本次唯一需要你留意的架構調整；其餘章節（Rule-based 抽取、Provider/Adapter 模式、狀態列舉、資料庫優先於向量庫等）完全照你的設計。

---

## 2. 整體系統架構圖

```text
                         ┌─────────────────────────┐
                         │   Frontend (React SPA)  │
                         │  上傳 / 分析 / 清單 / 報表 │
                         └────────────┬────────────┘
                                      │ REST (JSON)
                                      ▼
                         ┌─────────────────────────┐
                         │      FastAPI (API層)     │
                         │  routers / schemas       │
                         └────────────┬────────────┘
                                      │
                 ┌────────────────────┼─────────────────────┐
                 ▼                    ▼                     ▼
        ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐
        │ DocumentService │  │ ExtractionService │  │  ReportService    │
        └────────┬────────┘  └─────────┬─────────┘  └─────────┬────────┘
                 │                     │                       │
                 ▼                     ▼                       │
        ┌────────────────┐   ┌──────────────────────┐          │
        │ Document Parser │   │  Regulation Extractor │         │
        │ (docx/pdf/txt)  │   │  Rule → Dict → NER →  │         │
        └─────────────────┘   │  LLM fallback         │         │
                               └──────────┬───────────┘          │
                                          ▼                      │
                               ┌──────────────────────┐          │
                               │ Normalization Engine   │         │
                               │ (alias dictionary)     │         │
                               └──────────┬───────────┘          │
                                          ▼                      │
                               ┌──────────────────────┐          │
                               │  Matching Engine       │         │
                               │ rule/fuzzy first,      │         │
                               │ LLM fallback (可關閉)   │         │
                               └──────────┬───────────┘          │
                                          ▼                      │
                    ┌─────────────────────┴─────────────────────┐│
                    ▼                                           ▼│
          ┌──────────────────┐                        ┌──────────────────┐
          │ RegulationSource  │                        │  Enterprise DB    │
          │ Adapters (可插拔) │◄──────future───────────►│ (企業內部規範)     │
          │ Mock / TaiwanLaw/ │                        └──────────────────┘
          │ CNS / ISO / ASTM  │
          └──────────┬────────┘
                      ▼
          ┌───────────────────────┐
          │   PostgreSQL           │  ←── 唯一的事實資料庫（結構化、可稽核）
          │  documents/references/ │
          │  regulations/queries/  │
          │  jobs/ai_invocation_log│
          └───────────┬───────────┘
                      │（第二階段才啟用）
                      ▼
          ┌───────────────────────┐
          │  Vector DB (Qdrant)    │  ←── 語意搜尋，第一階段不啟用
          └───────────────────────┘

          ┌───────────────────────┐
          │  LLMProvider 介面      │  ← 被 Extractor / Matching / Report 呼叫
          │  Anthropic(預設)/OpenAI│     每次呼叫都寫入 ai_invocation_log
          │  /Gemini/Local(可抽換) │
          └───────────────────────┘
```

### 2.1 分析流程時序（一次上傳分析的完整生命週期）

```text
1. 使用者上傳 DOCX
   → POST /api/documents/upload
   → 驗證副檔名/大小/雜湊 → 寫入 documents (status=UPLOADED)
   → 立即回傳 document_id

2. 使用者按「開始分析」
   → POST /api/documents/{id}/analyze
   → 建立 jobs (status=PENDING)
   → 丟進 BackgroundTasks（未來可換 Celery）
   → 立即回傳 job_id（不等待）

3. 背景工作開始執行（jobs.status=PROCESSING）
   a. Document Parser 解析 DOCX → 寫入 document_sections（保留頁碼/段落/表格）
   b. Regulation Extractor 對每個 section 跑 Rule→Dict→NER→(可選)LLM fallback
      → 每筆候選寫入 regulation_references（raw_name, type, confidence, source=規則/LLM）
   c. Normalization Engine 用別名字典 + fuzzy string 比對，補上 normalized_name
   d. Matching Engine 對每筆 reference 找 regulations 表裡是否已有紀錄
      - 有 → 檢查是否需要重新查詢（依 TTL）
      - 沒有 → 呼叫 RegulationSource adapters（先是 MockRegulationSource）
      - 每次外部查詢都寫入 regulation_queries（含 raw_response）
   e. 依查詢結果更新 regulations 狀態（ACTIVE/AMENDED/REPEALED/NOT_FOUND/
      POSSIBLE_MATCH/UNKNOWN）與 regulation_references.status
   f. 若使用 LLM（抽取或判斷相似度），呼叫都寫入 ai_invocation_log
   g. jobs.status=COMPLETED，progress=100，寫入 finished_at
      （任何一步失敗 → jobs.status=FAILED + error_message，
       單一筆 reference 查詢失敗不影響整份文件，只標記該筆 status=UNKNOWN）

4. 前端輪詢 GET /api/jobs/{job_id} 顯示進度
5. 完成後前端呼叫 GET /api/documents/{id}/references 顯示清單
6. 使用者可對任一筆按「人工覆核」→ PATCH regulation_references 的 review_status
7. 使用者按「匯出報告」→ GET /api/reports/{document_id}/export?format=xlsx
```

---

## 3. 技術選型

| 分類 | 選擇 | 理由 |
|---|---|---|
| 後端框架 | Python 3.11+ / FastAPI | 需求書指定；原生支援 async、OpenAPI 文件自動生成 |
| ORM | SQLAlchemy 2.0 (async) + Alembic | 需求書指定 SQLAlchemy；Alembic 負責 `migrations/` |
| 驗證/序列化 | Pydantic v2 | 需求書指定；同時作為 API schema 與內部資料傳輸物件 |
| 資料庫 | PostgreSQL 15+ | 需求書指定，作為唯一事實來源 |
| 文件解析 | python-docx（DOCX）、PyMuPDF（PDF）、內建 `open()`（TXT） | 需求書指定；PyMuPDF 可同時取得頁碼與文字座標，利於保留頁碼 |
| 字串相似度 | rapidfuzz | 規則式比對優先於向量/LLM，符合第十二節「不要急著上向量庫」的原則；輕量、無需額外服務 |
| 背景任務 | FastAPI `BackgroundTasks`（`JobRunner` 介面包裝，未來可換 Celery+Redis） | 對應第十八節與確認的使用規模 |
| AI Provider | 抽象 `LLMProvider` 介面；預設實作 Anthropic Claude API | 你確認的預設值；其餘 Provider 之後補 |
| 向量資料庫 | 不啟用（Phase 1）；Phase 2 起用 Qdrant | 需求書第十二節明確要求 |
| 前端 | React 18 + Vite + TypeScript + 簡單元件庫（如 shadcn/ui 或 Ant Design，MVP 可先用陽春 CSS） | 見上方 1.7 的說明 |
| 報表匯出 | openpyxl（Excel）、csv（內建）、reportlab 或 WeasyPrint（PDF） | 常見成熟套件，授權皆友善 |
| 容器化 | Docker + docker-compose（backend / frontend / postgres，未來加 qdrant） | 對應確認的部署環境 |
| 測試 | pytest + pytest-asyncio + httpx（API 測試）+ testcontainers 或 sqlite fallback | 覆蓋 unit / integration / API 三層 |
| Log | 標準 `logging` + JSON formatter，依需求書第三十五節分類輸出 | 之後可無痛接 ELK / Loki |

---

## 4. 模組職責（對應 `backend/app/` 目錄）

- **api/**：只做 HTTP 層轉換（路由、參數解析、呼叫 service、組裝 response），不含業務邏輯。
- **schemas/**：Pydantic request/response 模型，與 DB model 分離，避免內部欄位外洩。
- **models/**：SQLAlchemy ORM 定義，對應第五章 database.md 的表結構。
- **repositories/**：純資料存取（CRUD + 查詢組合），不含業務判斷，方便單元測試時 mock。
- **services/**：業務邏輯編排（`DocumentService`、`ExtractionService`、`MatchingService`、`ReportService`、`JobService`），是唯一可以「跨多個 repository 做事」的層。
- **extractors/**：`RuleEngine`（正規表示式 + 字典）→ `NERExtractor`（可選，spaCy 或規則式 NER）→ `LLMExtractor`（fallback，呼叫 `ai/` 的 `LLMProvider`）。每一層都回傳同樣的候選格式，由上層決定要不要往下一層送。
- **matching/**：`NormalizationEngine`（別名字典查表 + 正規化規則）+ `MatchingEngine`（rapidfuzz 相似度 → 門檻以上直接判定 → 門檻以下且 `ENABLE_LLM_FALLBACK=true` 才問 LLM）。
- **sources/**：`RegulationSource` 抽象基底類別 + `MockRegulationSource`（Phase 1）+ 未來的 `TaiwanLawSource` / `CNSSource` / `ISOSource` / `ASTMSource` / `JISSource` / `EnterpriseRegulationSource`。
- **ai/**：`LLMProvider` 抽象介面 + `AnthropicProvider` 實作 + prompt 模板管理（含 `prompt_version`）+ structured output 解析與驗證（Pydantic 驗證 LLM 回傳的 JSON，驗證失敗要有重試/降級策略，絕不讓壞掉的 JSON 直接寫入資料庫）。
- **reports/**：`ExcelReportBuilder` / `CSVReportBuilder` / `PDFReportBuilder`，輸入統一的報告資料結構（不直接碰 DB）。
- **core/**（需求書目錄未列出，但必要）：`config.py`（讀取 `.env`）、`db.py`（DB session 管理）、`logging.py`（分類 log 設定）、`security.py`（檔案驗證、未來 API auth 預留）。
- **jobs/**（新增，對應 1.6 的 `JobRunner`）：`JobRunner` 介面 + `BackgroundTasksJobRunner` 實作。

---

## 5. AI 使用原則（落實你第十一、二十四節的規則）

**LLM 會被呼叫的地方（僅這幾處，且都可關閉/降級）：**

1. `extractors/llm_extractor.py`：當 Rule + Dictionary + NER 都沒抽到足夠信心的候選時，把該段落丟給 LLM 做 fallback 抽取，要求 Structured Output（見 database.md 的 `ai_invocation_log`）。
2. `matching/matching_engine.py`：當 rapidfuzz 相似度分數落在「不上不下」的模糊區間，且 `ENABLE_LLM_FALLBACK=true` 時，才問 LLM 做語意相似度判斷，作為輔助訊號之一，**不會覆蓋規則引擎的結果，只會補充「候選原因」欄位**。
3. `reports/`：把結構化查詢結果轉成人類可讀的文字說明（例如「此法規於 2026 年 5 月疑似修正，建議人工確認最新條文」），僅負責語言表達，不負責判斷本身。

**LLM 絕對不會被呼叫、也不允許成為真相來源的地方：**

- 法規「目前是否有效／廢止／修正」的最終判斷 → 只能來自 `RegulationSource` adapter 回傳的官方資料，或人工覆核（`review_status`）。
- 直接寫入 `regulations.status` → 一定要先經過 Matching Engine 依照官方查詢結果組裝，LLM 的輸出即使被使用，也只會落在 `ai_invocation_log` 與 `regulation_references` 的輔助欄位，不會直接寫入 `regulations` 主表。

每一次 LLM 呼叫，不論用途，都會記錄：`model`、`prompt_version`、`input`（去識別化後的段落）、`output`（原始 JSON）、`timestamp`、`confidence`，存入 `ai_invocation_log`，可回溯任何一筆判斷是哪個模型、哪個 prompt 版本產生的。

---

## 6. Provider / Adapter 設計細節

```python
# backend/app/sources/base.py
class RegulationSource(ABC):
    source_name: str  # 例如 "mock", "taiwan_law_moj", "cns"

    @abstractmethod
    async def search(self, query: str) -> list[RegulationSearchResult]: ...

    @abstractmethod
    async def get_detail(self, regulation_id: str) -> RegulationDetail | None: ...

    @abstractmethod
    async def get_version_history(self, regulation_id: str) -> list[RegulationVersion]: ...
```

- 所有 adapter 回傳都轉成統一的 `RegulationSearchResult` / `RegulationDetail`（對應需求書第八節的統一格式），呼叫端（Matching Engine）完全不知道資料是從哪個來源來的。
- 每個 adapter 內部自行處理該來源特有的錯誤（timeout / 4xx / 5xx / 無效 JSON），對外一律轉成統一的 `SourceQueryError`，並且**單一 adapter 失敗不會讓整份文件分析失敗**——由 `MatchingService` 捕捉例外，把該筆 reference 標記 `status=UNKNOWN`，繼續處理下一筆。
- `MockRegulationSource`：從 `data/mock_regulations.json`（或未來的 seed 資料）讀取，讓開發/測試/Demo 在完全沒有網路存取時也能跑通全流程，也作為未來真實 adapter 的行為規格範本。

`LLMProvider` 介面同理：

```python
# backend/app/ai/base.py
class LLMProvider(ABC):
    @abstractmethod
    async def extract_regulations(self, text: str, prompt_version: str) -> ExtractionResult: ...

    @abstractmethod
    async def judge_similarity(self, name_a: str, name_b: str, context: str) -> SimilarityJudgement: ...

    @abstractmethod
    async def summarize_for_report(self, references: list[RegulationReference]) -> str: ...
```

---

## 7. 非同步任務設計

```python
# backend/app/jobs/base.py
class JobRunner(ABC):
    @abstractmethod
    async def enqueue(self, job_id: UUID, document_id: UUID) -> None: ...

    @abstractmethod
    async def get_status(self, job_id: UUID) -> JobStatus: ...
```

第一版 `BackgroundTasksJobRunner` 直接呼叫 `ExtractionService.run_pipeline(document_id, job_id)`，管線內每一步都更新 `jobs.progress` 與 `jobs.current_step`，讓前端可以顯示「解析中 → 抽取中 → 查詢中 → 產生報告中」。之後若要換 Celery，只需要新增 `CeleryJobRunner`，把 `enqueue` 改成 `.delay(...)`，其餘程式碼不動。

---

## 8. 安全設計（MVP 範圍）

- 上傳檔案：限制副檔名白名單（`.docx/.pdf/.txt`）、限制大小（例如 50MB，可設定）、以檔案內容雜湊（SHA-256）去重、儲存路徑與原始檔名分離（避免 path traversal）。
- `.env`／API Key：一律透過環境變數注入，`.env` 加入 `.gitignore`，`.env.example` 只列出變數名稱。
- SQL Injection：全面透過 SQLAlchemy ORM／參數化查詢，不手刻字串拼接 SQL。
- Prompt Injection 基本防護：送進 LLM 的文件內容視為不可信輸入，prompt 模板明確區隔「系統指令」與「文件內容」，並要求 Structured Output＋Pydantic 驗證，驗證失敗即丟棄該次結果並記錄，不重試以模型自由發揮的方式修正。
- API Authentication：使用本機帳密與 Argon2 密碼雜湊，資料庫保存可撤銷 session 的雜湊；cookie 使用 HttpOnly、SameSite=Lax，正式環境啟用 Secure。登入身分由 FastAPI dependency 注入服務，所有業務 API 執行租戶範圍檢查；租戶管理員管理同租戶成員。

---

## 9. 未來產品化架構（沿用你的設計，補充落地方式）

```text
文件上傳 → Document Parser → Regulation Extraction → Normalization Engine
   → Matching Engine → [Official APIs | Enterprise DB] → (Phase2)RAG Layer
   → (Phase2)AI Agent → (Phase3)Compliance Analysis → Report
```

目前已有單一部署內的租戶帳號與資料隔離基礎。企業級 SaaS 仍需補上備份／還原與監控等營運能力；也可以維持每個客戶獨立部署。

---

## 10. 原始 Phase 0 確認事項（歷史紀錄）

1. 第 1.7 點：前端用 React+Vite 還是 Jinja2+htmx？（我先按 React+Vite 走）
2. 官方法規資料來源的調研：這次環境內網路存取受限，無法完成。是否由你提供任何你已知的政府開放資料網址／API 文件？或是我在後續有網路存取的階段再重新嘗試調研？
3. 檔案大小上限、支援語言（是否只需要繁體中文文件）等細節參數，若沒有特殊需求，我會採用文件中列出的合理預設值。
