# 開發計畫（Phase 0）

---

## 1. 專案目錄結構

```text
engineering-regulation-platform/
│
├── backend/
│   ├── app/
│   │   ├── api/                # FastAPI routers
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/              # Pydantic request/response
│   │   ├── services/             # 業務邏輯編排
│   │   ├── repositories/         # 純資料存取
│   │   ├── extractors/           # Rule/Dictionary/NER/LLM 抽取
│   │   ├── matching/              # Normalization + Matching Engine
│   │   ├── sources/               # RegulationSource adapters
│   │   ├── ai/                    # LLMProvider 介面與實作
│   │   ├── jobs/                  # JobRunner 介面與 BackgroundTasks 實作
│   │   ├── reports/               # Excel/CSV/PDF 產生器
│   │   ├── core/                  # config/db/logging/security
│   │   └── main.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── api/
│
├── frontend/                     # React + Vite + TypeScript
│
├── data/                         # Mock 資料、別名字典種子資料
│
├── migrations/                   # Alembic
│
├── scripts/                      # seed_data.py 等維運腳本
│
├── docker/
│
├── docs/
│   ├── architecture.md
│   ├── database.md
│   ├── api.md
│   └── development-plan.md
│
├── .env.example
├── docker-compose.yml
├── README.md
└── requirements.txt
```

---

## 2. MVP 開發順序（對應需求書第三十七節 Phase 0–15）

每個 Phase 結束都遵守你要求的節奏：**Plan → Implement → Test → Run → Fix → Document**，並實際跑一次 `docker compose up` 驗證（Phase 13 之前用本機 `uvicorn` + 本機 postgres 驗證即可）。

| Phase | 內容 | 完成標準（可驗收） |
|---|---|---|
| 0 | 專案分析 + 架構設計 | 本次四份文件（本文件即產出） |
| 1 | 專案骨架：目錄結構、`.env.example`、`requirements.txt`、`core/config.py` | `python -m app.main` 可啟動空白 FastAPI，`/api/health` 回 200 |
| 2 | 資料庫：建立所有 model + 第一版 Alembic migration | `alembic upgrade head` 成功建表，`psql` 可查到所有表 |
| 3 | Document Parser：DOCX/PDF/TXT 解析，寫入 `documents`/`document_sections` | 對 3 種格式各跑一份範例文件，段落/頁碼/表格內容正確落地 DB |
| 4 | Regulation Extractor：Regex + Dictionary 規則引擎（先不做 NER/LLM） | 針對你提供的範例句子（政府採購法第○○條 / CNS 1234）能正確抽出結構化欄位 |
| 5 | Regulation Reference List：整合抽取結果寫入 `regulation_references`，含 `extraction_method`/`extraction_confidence` | 一份完整文件跑完後，DB 內可查到完整清單 |
| 6 | Normalization Engine + `RegulationSource` 介面定義 | 別名字典可將「採購法」正規化為「政府採購法」；介面定義完成但尚無實作 |
| 7 | `MockRegulationSource` 實作 + 種子資料 | 呼叫介面可回傳假資料，且符合統一格式（第 8 節格式） |
| 8 | 真實官方資料來源串接 | **已完成（2026-09）**：接上法務部全國法規資料庫 Open API，法律 1,346 筆 + 命令 10,447 筆。見下方「Phase 8 實作結果」 |
| 9 | Matching Engine：rapidfuzz 相似度 + 門檻邏輯 + LLM fallback（可透過 `ENABLE_LLM_FALLBACK` 關閉） | 針對「採購法 → 政府採購法」等測試案例，信心分數與比對理由符合預期 |
| 10 | API 層：串接所有 Phase 3–9 的 service，補齊 `jobs` 輪詢與人工覆核 endpoint | 用 `httpx`/Postman 走完一次完整流程（upload → analyze → 輪詢 → references → review → report） |
| 11 | Frontend：上傳、分析進度、清單（含篩選）、詳細面板、人工覆核操作 | 手動操作一次完整流程，UI 顯示與 API 回應一致 |
| 12 | Report：Excel/CSV/PDF 匯出 | 三種格式都能正確匯出，欄位符合第十六節報告格式 |
| 13 | Docker 化：`docker-compose.yml`（backend/frontend/postgres） | `docker compose up` 後從瀏覽器可直接操作完整流程 |
| 14 | 測試補強：Unit（抽取/正規化/比對/狀態映射）、Integration（DOCX→DB全鏈路）、API 測試 | `pytest` 全綠，並涵蓋需求書第二十三節列出的項目 |
| 15 | Deployment Guide + README 更新 | 依 README 指示的人可以從零把系統跑起來 |

### Phase 8 實作結果（官方資料來源串接）

**已完成。** 實際查證並接上法務部全國法規資料庫 Open API：

- Endpoint：`https://law.moj.gov.tw/api/{Ch|En}/{Law|Order}/JSON`（swagger 在 `/api/swagger`，spec 在 `/api/swagger/docs/v1`）
- 回傳 ZIP 批次下載，非逐筆查詢 → 實作成 `scripts/sync_taiwan_law.py` 同步 + `TaiwanLawSource` 從索引查詢
- 授權：政府資料開放授權條款第 1 版（GODL v1.0），可商用，需註明出處
- 涵蓋範圍：**只有法律與法規命令**。行政規則／作業要點、工程規範、CNS/ISO/ASTM/JIS 都不在內，仍需其他來源或人工查證
- 官方資料庫**不保留已更名法規的舊名**（例如「勞工安全衛生法」），舊名對應仍要靠 `data/alias_dictionary.json`

以下是實作前的原始說明，保留作為當時的判斷紀錄：


依你的回覆，這部分目前「尚無串接經驗」，而本次 Phase 0 嘗試調研時，此環境對 `law.moj.gov.tw`、`data.gov.tw` 等網域的存取被 robots.txt／代理層擋下，**無法在本次對話中完成即時查證**（WebSearch 工具本身也回傳 403，研判是此沙盒環境的網路限制，非法規網站問題）。

依照你在需求書第三十二節的明確要求（不要自行假設法規 API），Phase 8 在 MVP 階段的處理方式是：

1. `RegulationSource` 介面與 `MockRegulationSource` 一定會在 Phase 6–7 完成，整個系統可以在完全沒有真實官方資料來源的狀況下端到端跑通（含報告、匯出）。
2. 真實來源串接分兩種狀況推進，擇一即可：
   - 你提供你已知或已測試過的政府開放資料網址、API 文件、或資料下載連結，我依文件實作對應 adapter；
   - 或等你、我任一方在有網路存取的環境重新查證後（例如你直接瀏覽 https://law.moj.gov.tw 或 https://data.gov.tw 搜尋「法規」相關資料集），把找到的 API／資料格式提供給我。
3. CNS／ISO／ASTM／JIS 這類國家/國際標準，就我所知多數屬於「有償標準」（需付費購買全文），公開來源通常只能查到「標準是否存在／最新版號」，查不到全文內容——這點無論串接與否都會存在，屬於**架構限制而非實作問題**，建議報告設計上就假設這類引用多半會落在 `POSSIBLE_MATCH`/`NOT_FOUND`，需要人工查證，而不是承諾系統能自動判斷這類標準的最新有效性。

---

## 3. 風險清單

| 風險 | 影響 | 因應方式 |
|---|---|---|
| 官方法規/標準來源缺乏公開 API（尤其 CNS/ISO/ASTM/JIS 多為付費標準） | Phase 8、後續符合性分析的準確度受限 | 明確在報告與 UI 上標示「來源：Mock／未確認」，鼓勵人工查證；`RegulationSource` 介面設計成之後可逐一補齊，不影響其餘模組 |
| 法規名稱高度模糊、簡稱多，造成 false positive/negative | 清單可信度、使用者信任度 | 別名字典 + 信心分數門檻可調整；所有比對都附「比對理由」供人工判讀，非黑箱 |
| LLM 產生看似合理但錯誤的法規狀態判斷（幻覺） | 誤導使用者做出錯誤判斷 | 架構上明確禁止 LLM 直接寫入 `regulations.status`；所有 LLM 輸出都記錄在 `ai_invocation_log` 可回溯 |
| 文件格式多樣（掃描版 PDF、複雜表格、圖片內文字） | Phase 3 解析失敗或漏抽 | **已加入 OCR（2026-10）**：文字不足且有圖的 PDF 頁送 Tesseract（PyMuPDF 內建，`chi_tra+eng`），辨識段落標記 `is_ocr` 並計入解析品質警告。範例掃描檔實測漏抽 26 筆中的 2 筆、讀錯 1 筆，錯字仍需人工對照 |
| 法規版本/生效日資料不完整或不一致 | 版本比對結果不可靠 | `regulation_versions` 允許欄位為 NULL，报告清楚標示「未知」而非猜測 |
| 大文件解析與查詢耗時 | 使用者體驗、背景任務逾時 | `jobs` 進度回報 + 逐步 log；未來量大時平移到 Celery（見 architecture.md 1.6） |
| 上傳檔案安全（惡意巨集、超大檔案、偽造副檔名） | 系統穩定性與安全性 | 副檔名白名單＋MIME 檢查＋大小限制＋雜湊去重；巨集內容不執行，僅用函式庫解析文字 |
| 政府開放資料授權條款未確認 | 若資料集有特定引用/使用限制，日後商用可能有合規疑慮 | 串接前逐一確認資料集授權條款（多數台灣政府開放資料為 CC BY 或政府資料開放授權，但需逐一核實，不假設） |
| 單一 LLM Provider 過度耦合 | 未來更換模型/供應商成本高 | `LLMProvider` 介面已抽象化，prompt 模板與 `prompt_version` 獨立管理 |
| 租戶隔離若晚加入 | 破壞性 migration 與資料外洩風險 | 已完成租戶根資料範圍、帳號角色及既有資料回填；更完整的 SaaS 營運能力仍待後續規劃 |

---

## 4. Definition of Done（MVP，對應需求書第三十八節）

```bash
docker compose up
```

開啟 Web，上傳「整體品質計畫.docx」，按「開始分析」，系統自動完成：

```text
DOCX → 文字解析 → 法規/規範抽取 → Reference List → 標準化
     → 查詢 MockRegulationSource → Matching → Status → Report
```

畫面顯示類似：

```text
政府採購法       ACTIVE          98%
CNS XXXX         POSSIBLE_MATCH  92%
XXXX施工規範     AMENDED（疑似） 76%
XXXX辦法         NOT_FOUND       41%
```

每一筆都可追溯：來源文件、頁碼、原始文字、比對到的法規、資料來源（含 Mock 標示）、查詢時間、AI 使用的模型與判斷內容（若有使用 LLM）、目前是否已人工覆核。

**與需求書原文的差異只有一點**：MVP 完成時串接的資料來源是 `MockRegulationSource`，不是真實官方 API（原因見上方 Phase 8 說明）。真實資料來源接上之後，整個流程與 UI 不需要改動，只是 `source` 欄位與查詢結果會換成真實資料。

---

## 5. 未來三階段路線圖（延續需求書第二十八、二十九節）

**Phase 2（RAG / 語意能力）**：Vector DB（Qdrant）僅收錄「已確定需要語意搜尋」的內容（文件段落全文、法規條文全文、企業內部規範），不是把 Phase 1 所有資料都倒進去；LLM Agent 開始承擔「法規問答」「跨文件比較」，但比對真相仍以 Layer 1（PostgreSQL + 官方來源）為準，Vector DB 只負責「找得到相關內容」，不負責「這是不是最新有效版本」。

**Phase 3（產品化 / 企業導入）**：法規異動監控（排程重新查詢已存在的 `regulations`，比對 `content_hash`/`last_amended_date` 是否變動 → 觸發通知）、企業知識庫（`EnterpriseRegulationSource` adapter + 企業自有別名字典）、進階權限與租戶生命週期管理（現有版本提供租戶管理員與一般成員，並隔離核心業務資料）、Audit Log（在現有 `ai_invocation_log`/`regulation_queries`/`review_status` 的基礎上，再加一張全域 `audit_log` 記錄誰在何時對什麼資源做了什麼操作）、Dashboard（彙總統計，資料來源就是既有的結構化表，不需要新的資料模型)。

---

## 6. 下一步

Phase 0 到此為止，尚未寫任何應用程式碼。等你確認以下事項後，我會開始 Phase 1（專案骨架）：

1. `architecture.md` 第 10 節列出的 3 個待確認事項（前端框架選擇、官方資料來源後續調研方式、上傳檔案大小等預設參數是否 OK）。
2. 本文件列出的 Phase 8 特別說明是否可以接受（MVP 先用 Mock，真實串接列為後續事項）。
3. 整體 15 個 Phase 的順序是否需要調整優先順序（例如你想先看到 UI，還是先確保後端資料正確）。
