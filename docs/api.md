# API 設計（Phase 0）

框架：FastAPI（自動產生 OpenAPI/Swagger，實際欄位以 `/docs` 為準，本文件是設計規格）
所有回應統一使用 JSON；錯誤回應統一格式（見第 5 節）。

---

## 1. 文件管理

### `POST /api/documents/upload`

上傳工程文件（multipart/form-data）。

請求：`file`（必填，`.docx/.pdf/.txt`，大小上限預設 50MB，可設定）

回應 `201`：
```json
{
  "document_id": "uuid",
  "filename": "整體品質計畫.docx",
  "file_type": "docx",
  "status": "UPLOADED",
  "uploaded_at": "2026-09-07T10:00:00+08:00"
}
```

錯誤：`400` 檔案型別不符 / 超過大小上限、`409` 檔案雜湊重複（可選擇是否允許重複上傳）。

### `GET /api/documents`

列出文件（分頁）。Query：`page`、`page_size`、`status`（篩選）。

### `GET /api/documents/{document_id}`

回傳文件 metadata 與目前狀態。

```json
{
  "document_id": "uuid",
  "filename": "整體品質計畫.docx",
  "status": "ANALYZED",
  "uploaded_at": "...",
  "latest_job": { "job_id": "uuid", "status": "COMPLETED", "finished_at": "..." }
}
```

---

## 2. 分析任務

### `POST /api/documents/{document_id}/analyze`

觸發背景分析（建立一筆 `jobs`）。可重複呼叫（重新分析），每次呼叫產生新的 `job_id`，不覆蓋歷史紀錄。

回應 `202`：
```json
{ "job_id": "uuid", "status": "PENDING" }
```

### `GET /api/jobs/{job_id}`

輪詢分析進度。

```json
{
  "job_id": "uuid",
  "document_id": "uuid",
  "status": "PROCESSING",
  "current_step": "MATCHING",
  "progress": 62,
  "started_at": "...",
  "error_message": null
}
```

---

## 3. 法規引用清單

### `GET /api/documents/{document_id}/references`

Query 參數：
- `status`：篩選 `ACTIVE/AMENDED/REPEALED/NOT_FOUND/POSSIBLE_MATCH/UNKNOWN`
- `review_status`：篩選 `UNREVIEWED/CONFIRMED/REJECTED`
- `min_confidence`：篩選信心分數下限
- `page` / `page_size`

回應：
```json
{
  "total": 35,
  "summary": {
    "confirmed_active": 27,
    "possible_amended": 3,
    "possible_repealed": 1,
    "unknown": 4
  },
  "items": [
    {
      "reference_id": "uuid",
      "raw_text": "採購法",
      "normalized_name": "政府採購法",
      "regulation_type": "law",
      "page": 12,
      "status": "ACTIVE",
      "match_confidence": 0.96,
      "review_status": "UNREVIEWED",
      "regulation_id": "uuid"
    }
  ]
}
```

### `GET /api/regulation-references/{reference_id}`

單筆詳細資料（對應前端「詳細資訊」面板）：

```json
{
  "reference_id": "uuid",
  "raw_text": "採購法",
  "source_document": "整體品質計畫.docx",
  "page": 12,
  "extraction_method": "dictionary",
  "extraction_confidence": 1.0,
  "matched_regulation": {
    "regulation_id": "uuid",
    "name": "政府採購法",
    "type": "law",
    "status": "ACTIVE",
    "authority": "行政院公共工程委員會",
    "effective_date": "...",
    "last_amended_date": "...",
    "official_url": "...",
    "source": "mock"
  },
  "match_confidence": 0.96,
  "match_reasons": ["Alias match", "名稱高度相似"],
  "review_status": "UNREVIEWED",
  "query_history": [
    { "source": "mock", "queried_at": "...", "http_status": "200" }
  ],
  "ai_invocations": [
    { "purpose": "similarity_judgement", "model": "claude-sonnet-5", "prompt_version": "matcher_v1", "confidence": 0.9 }
  ]
}
```

### `PATCH /api/regulation-references/{reference_id}/review`（人工覆核，對應 architecture.md 1.3）

請求：
```json
{ "review_status": "CONFIRMED", "reviewed_by": "kayla3377@gmail.com", "review_note": "已人工核對官網條文" }
```

回應 `200`：更新後的 reference 詳細資料。

---

## 4. 法規查詢

### `GET /api/regulations/search`

Query：`q`（查詢字串）、`type`（可選）。先查內部 `regulations` 表，找不到時可加 `force_external=true` 觸發即時查詢已註冊的 `RegulationSource` adapters。

### `GET /api/regulations/{regulation_id}`

回傳法規詳細（含 aliases、versions、最近查詢紀錄）。

### `POST /api/regulations/verify`

手動觸發重新查詢外部來源（例如使用者懷疑資料過期）。

請求：
```json
{ "regulation_id": "uuid", "source": "mock" }
```
`source` 省略則查詢所有已註冊 adapter。

---

## 5. 報告

### `GET /api/reports/{document_id}`

回傳報告摘要（JSON，供前端畫面顯示，對應需求書第十六節）。

### `GET /api/reports/{document_id}/export?format=xlsx|csv|pdf`

回傳檔案下載（`Content-Disposition: attachment`）。

---

## 6. 錯誤格式（統一）

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "找不到指定的文件",
    "details": null
  }
}
```

常見對應：

| HTTP | code 範例 | 情境 |
|---|---|---|
| 400 | `INVALID_FILE_TYPE` / `VALIDATION_ERROR` | 檔案型別不符、請求格式錯誤 |
| 404 | `DOCUMENT_NOT_FOUND` / `REGULATION_NOT_FOUND` | 資源不存在 |
| 409 | `DUPLICATE_FILE` | 檔案雜湊重複 |
| 422 | `UNPROCESSABLE_DOCUMENT` | 解析失敗（例如加密/損毀檔案） |
| 500 | `INTERNAL_ERROR` | 未預期錯誤（不外洩堆疊細節給前端，完整內容寫入 log） |

外部來源查詢（`sources/` adapter）發生 timeout / 4xx / 5xx / JSON 解析失敗時，**不會**變成 API 500，而是被 `MatchingService` 捕捉，該筆 reference 標記 `status=UNKNOWN`，並在 `regulation_queries` 留下錯誤紀錄，整體分析流程繼續完成。

該筆的 `match_reasons` 會寫進失敗原因與下一步。來源自己有給補救動作（`SourceQueryError.remedy`，例如索引還沒同步）時就直接寫出命令；沒有補救動作的暫時性失敗才會請使用者稍後重試：

```
外部來源查詢失敗：找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）（請執行：python scripts/sync_taiwan_law.py）
外部來源查詢失敗：連線逾時（已記錄於查詢紀錄，可稍後重試）
```

---

## 7. 健康檢查與版本

### `GET /api/health`

供 docker-compose healthcheck 與未來監控使用。

```json
{ "status": "ok", "database": "ok", "version": "0.1.0" }
```

### `GET /api/sources`

回報每個已啟用的法規來源現在查不查得動。

存在的理由：官方索引是 `scripts/sync_taiwan_law.py` 同步下來的本地檔案，「有沒有跑過同步」是部署方的責任。沒跑的話分析仍會完成，但每一筆引用都會是 `UNKNOWN`。前端在使用者按下「開始分析」之前就打這支 API，才能把原因講出來，而不是讓人對著整頁 `UNKNOWN` 猜。

```json
{
  "status": "degraded",
  "sources": [
    {
      "source": "taiwan_law",
      "ready": false,
      "detail": "找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）",
      "remedy": "python scripts/sync_taiwan_law.py"
    },
    { "source": "mock", "ready": true, "detail": null, "remedy": null }
  ]
}
```

| `status` | 意義 | 前端行為 |
|---|---|---|
| `ok` | 全部來源就緒 | 不顯示任何提示 |
| `degraded` | 部分來源未就緒：查得到，但涵蓋範圍比預期小 | 黃色提醒橫幅 |
| `unavailable` | 沒有任何來源就緒（含一個來源都沒啟用）：每一筆引用都會是 `UNKNOWN` | 紅色警告橫幅 |

`detail` 是給人看的完整句子（含檔案路徑），`remedy` 是可以直接複製執行的命令；沒有可執行的動作時 `remedy` 為 `null`，前端就不顯示指示。

每次呼叫都重新檢查（載入失敗不會被快取），所以跑完同步腳本之後不需要重啟服務，前端重新整理就會恢復。
