# API 設計（Phase 0）

框架：FastAPI（自動產生 OpenAPI/Swagger，實際欄位以 `/docs` 為準，本文件是設計規格）
所有回應統一使用 JSON；錯誤回應統一格式（見第 5 節）。

## 0. 登入與帳號

除 `GET /api/health`、`GET /api/sources` 和 `POST /api/auth/login` 外，所有 API 都需要登入。未登入回傳 401；一般成員呼叫管理員 API 回傳 403；不存在或不屬於目前租戶的資源都回傳相同 404。瀏覽器使用 HttpOnly、SameSite=Lax 的 `eq_session` cookie；正式環境必須啟用 `AUTH_COOKIE_SECURE` 並使用 HTTPS。寫入請求會檢查 Origin。租戶 ID 從 session 取得，不接受客戶端指定。

### `POST /api/auth/login`

請求 `{ "username": "admin", "password": "…" }`。成功時回傳使用者／租戶摘要並設置 session cookie；失敗統一回傳 401。

登入嘗試由資料庫共享限流，依正規化帳號與來源 IP 在 `AUTH_LOGIN_WINDOW_SECONDS` 滑動時間窗內計數；超過 `AUTH_MAX_LOGIN_ATTEMPTS` 時回傳 429。成功登入會清除該組嘗試紀錄。

### `GET /api/auth/me`、`POST /api/auth/logout`

`me` 回傳目前使用者和 `must_change_password`。登出撤銷目前 session 並清除 cookie。

### `POST /api/auth/change-password`

請求 `{ "old_password": "…", "new_password": "至少 12 字元" }`。首次登入被要求改密碼時可省略 `old_password`。密碼更新會撤銷該帳號所有 session，使用者需重新登入。

### 使用者管理

`GET /api/users`、`POST /api/users`、`PATCH /api/users/{user_id}` 僅限租戶管理員。新增請求包含 `username` 和 `initial_password`，`role` 可為 `member` 或 `tenant_admin`（省略時為 `member`）；租戶 ID 一律取自登入管理員。`PATCH` 使用 `{"is_active": false}` 停用帳號，並使用 `{"is_active": true, "initial_password": "..."}` 重新啟用。重新啟用會重設密碼、要求使用者首次登入時變更，並撤銷既有工作階段。一般成員與跨租戶 ID 均不能管理帳號。

### 首位管理員

完成資料庫 migration 後，在後端執行 `python scripts/bootstrap_admin.py --tenant-name "租戶名稱" --username admin`，密碼會透過隱藏提示輸入。此部署已有有效管理員時不允許再次 bootstrap。

管理員忘記密碼時，部署操作員可執行 `python scripts/reset_user_password.py --username admin`，並在隱藏提示中輸入新密碼。此操作要求下次登入更改密碼並撤銷既有 session，不會啟用停用帳號。

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
  "parse_quality": "OK",
  "parse_quality_note": null,
  "uploaded_at": "...",
  "latest_job": { "job_id": "uuid", "status": "COMPLETED", "finished_at": "..." }
}
```

#### `parse_quality`：解析到的內容可不可信

`status: ANALYZED` 只代表流程跑完了，不代表內容讀得完整。設計圖說的尺寸標註與
構件名稱壓在點陣圖裡，PDF 解析器抽得到圖號和標題欄，**抽不到圖裡的字**——然後
安靜地回傳一份近乎空白的結果。那是「有信心的錯」，比解析失敗更難發現。

| 值 | 意義 |
|---|---|
| `OK` | 沒有偵測到內容遺失 |
| `DEGRADED` | 有相當比例的頁面以圖為主，圖內文字未被讀取。段落照常存、分析照常完成，但**結果不可盡信** |

`parse_quality_note` 只有 `DEGRADED` 時有值，會寫出實際數字：

```json
{
  "parse_quality": "DEGRADED",
  "parse_quality_note": "105 頁裡有 57 頁以圖為主，圖內的文字（尺寸標註、構件名稱等）未被讀取"
}
```

判定規則：一頁的可選取文字少於 200 字**且**該頁有圖片，就算「以圖為主」；這種頁
佔全文件 10% 以上就標記為 `DEGRADED`。門檻校準自 4 份真實工程文件，實測圖頁佔比
0%、0.8%、22%、54%——後兩份被標記，前兩份放行。

門檻刻意訂得寬鬆：這一層不擋文件也不中斷分析，誤報只是多一行警告，漏報卻會讓人
拿著一份空結果當成「查無問題」。樣本只有 4 份，拿到更多文件（特別是契約圖）之後
會重新校準。只有 PDF 會做這個判定，其他格式一律 `OK`。

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
{ "review_status": "CONFIRMED", "review_note": "已人工核對官網條文" }
```

`reviewed_by` 由登入 session 的使用者名稱產生，客戶端不可自行指定。

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

## 6.5 專案與工項

專案是加在 `documents` 之上的一層：同一份文件仍然走原本的上傳→解析→抽取流程，
專案只記錄「這份文件在這個專案裡扮演什麼角色」。

**角色決定跑什麼管線**：標單走工項抽取，契約與規範走法規抽取。把法規抽取跑在
標單上只會得到滿頁 `NOT_FOUND`——實測抽到 40 筆引用，其中 38 筆（95%）查無此法規，
剩下 2 筆也只到 `POSSIBLE_MATCH`，沒有一筆是確定的。同一套抽取跑在品質計畫上，
NOT_FOUND 只佔 4%（26 筆裡 1 筆）。差別不在抽取器，在文件型別。

| `role` | 意義 |
|---|---|
| `boq` | 標單（詳細價目表）。工項清單的來源 |
| `contract` | 契約書 |
| `drawing` | 契約圖 |
| `specification` | 施工規範（常是契約附件） |
| `other` | 其他 |

### `POST /api/projects`

`{"name": "秀山分隊興建工程"}` → 201，回 `{project_id, name, created_at}`。
名稱只有空白會是 400。

### `GET /api/projects`

`{"total": 1, "items": [...]}`

### `POST /api/projects/{project_id}/documents`

`{"document_id": "...", "role": "boq"}` → 201。同一份文件在同一個專案裡只能掛一次，
重複掛是 400；專案不存在是 404 `PROJECT_NOT_FOUND`。同一個角色掛了不只一份文件時，建工項清單
與建檢核表都取最早掛上去的那一份（`added_at`；同一時刻掛的依 id），每次都是同一份。

### `POST /api/projects/{project_id}/work-items`

從專案的標單重建工項清單，**取代**舊的而不是累加。沒掛標單是 400，訊息會說明
「這個專案還沒有掛標單，沒有工項來源」。

### `GET /api/projects/{project_id}/work-items`

```json
{
  "total": 1028,
  "with_spec_chapter": 438,
  "items": [
    {
      "work_item_id": "...",
      "item_no": "壹.一.1.1.1",
      "name": "施工測量，基地測量及鑑界費",
      "unit": "式",
      "quantity": "1",
      "cost_code": "0172500004",
      "spec_chapter": {"code": "01725", "name": "公共工程施工綱要規範第01725章 施工測量"}
    }
  ]
}
```

`spec_chapter` 由計價代碼前 5 碼查施工綱要規範目錄得到。對不到就是 `null`——
各機關自訂的專業工項不在共通性工項目錄裡。實測真實標單 1028 個工項：513 個有計價
代碼，其中 438 個對得到章節（佔有代碼者 85%、佔全部工項 43%）。兩個數字要分開看：
有代碼的話命中率很高，但只有一半的工項有代碼。

---

## 6.6 工項檢核表

檢核表把 6.5 節的每個工項，對上它在**本案施工規範書**（角色 `specification`）裡的章節，
以及該章「相關準則」列出的法規與標準。檢核結果（`result`）不存在資料庫裡，每次回應時
由工項、章節索引與依據算出來。

**建與讀是兩支 API：POST 重建，GET 只讀已經建好的。** GET 不會順手重建——重建要重讀整份
規範書、對每個工項重新抽取，而且有副作用的 GET 會讓人無法回答「為什麼數字變了」。所以：

- 從沒 POST 過的專案，GET 照樣回得出工項，但每一列都沒有章節（`chapter`）與依據，全是
  `NEEDS_CONFIRMATION`；`chapter_code` 照樣有，它只看工項自己的計價代碼。
- 工項清單重建（`POST /work-items`）之後，新的工項還沒有依據，要再 POST 一次檢核表。

### `POST /api/projects/{project_id}/checklist`

重建依據並回傳檢核表（201，內容同下面的 GET）。重跑取代，不累加。專案不存在是 404
`PROJECT_NOT_FOUND`。

**沒掛施工規範不會報錯**——檢核表照樣產出，只是依據欄空白。工項清單本身有價值。
這和沒掛標單是 400 刻意不對稱：沒有標單，表是空的；沒有規範書，表還在。

規範書讀不懂（打不開、已加密、找不到任何章節頁首）是 422 `UNPROCESSABLE_DOCUMENT`，
上一次建好的章節索引與依據原封不動。這裡不會安靜地產出一張全部 `NEEDS_CONFIRMATION`
的表：那看起來像「這個案子沒有依據」，實際是「沒讀懂規範書」。

### `GET /api/projects/{project_id}/checklist`

只讀已經建好的依據，不重建。專案不存在是 404 `PROJECT_NOT_FOUND`。

```json
{
  "total": 1028,
  "summary": { "ok": 248, "spec_not_included": 188, "needs_confirmation": 592 },
  "contract_note": "契約文件優先順序：招標文件內之標價清單…",
  "spec_warning": null,
  "items": [
    {
      "work_item_id": "...",
      "item_no": "壹.一.1.1.1",
      "name": "施工測量，基地測量及鑑界費(測量儀器屬施工中由承商建置，採租用屬臨時設施及雜項作業設施)",
      "result": "NEEDS_CONFIRMATION",
      "chapter_code": "01725",
      "chapter": { "code": "01725", "title": "施工測量", "version": "3.0" },
      "bases": []
    },
    {
      "work_item_id": "...",
      "item_no": "壹.一.1.1.5",
      "name": "臨時設施，施工用臨時水電設施費(含申請費)",
      "result": "SPEC_NOT_INCLUDED",
      "chapter_code": "01510",
      "chapter": null,
      "bases": []
    },
    {
      "work_item_id": "...",
      "item_no": "壹.一.1.4.8",
      "name": "水泥漆，平頂披水泥磨平刷綠建材水性水泥漆",
      "result": "OK",
      "chapter_code": "09912",
      "chapter": { "code": "09912", "title": "水泥漆", "version": "5.0" },
      "bases": [
        { "basis_type": "standard", "reference": "中華民國國家標準", "detail": "第09912章 相關準則",
          "verification_status": null },
        { "basis_type": "standard", "reference": "CNS 4940", "detail": "第09912章 相關準則",
          "verification_status": null },
        { "basis_type": "standard", "reference": "CNS 8144", "detail": "第09912章 相關準則",
          "verification_status": null }
      ]
    }
  ]
}
```

範例取自真實標單與規範書的實測結果，三筆各取一種結果；`items` 實際有 1028 筆，順序同 6.5 節
的工項清單，`work_item_id` 也和工項清單的是同一個。第一筆說明 `NEEDS_CONFIRMATION` 不一定
是「找不到章節」：01725 施工測量在本案規範書裡，只是這一章沒有宣告相關準則。

`chapter_code` 是工項計價代碼的前 5 碼（和比對章節用的是同一個規則），沒有計價代碼時是
`null`。它和 `chapter` 不同：`chapter` 是**本案規範書裡**對得到的那一章，`chapter_code` 只取決
於工項自己，所以第二筆（`SPEC_NOT_INCLUDED`，`chapter` 是 `null`）也有——要依章分流那一批，章碼
只能從這裡拿。有 `chapter` 的列，`chapter_code` 一定等於 `chapter.code`。它只是代碼的前 5 碼，
不保證是真的章：實測有 74 個工項（17 個章碼）的代碼既不在本案規範書、也不是施工綱要規範的
任何一章，這些列有 `chapter_code`，`chapter` 是 `null`，`result` 是 `NEEDS_CONFIRMATION`。
`chapter` 是 `null` 的列沒有章名：`SPEC_NOT_INCLUDED` 的列要章名，看 `GET /work-items` 裡同一個
`work_item_id` 的 `spec_chapter.name`（施工綱要規範目錄的章名；實測這 188 筆都有）。

`result` 三個值。下面的數字是 2026-10-07 在真實標單（`2.契約書.xls`，1028 個工項）與真實
規範書（`13.施工規範.pdf`，772 頁、86 章）上**實測**的：

| 值 | 意義 |
|---|---|
| `OK` | 章節在本案規範書裡，且該章宣告了相關準則（`bases` 不是空的）。實測 248 筆（24%） |
| `SPEC_NOT_INCLUDED` | 計價代碼對得到施工綱要規範的章節，但**本案規範書沒收錄該章**（`chapter` 是 `null`）。實測 188 筆（18%），分屬 26 章，**要分流，不是 188 個漏洞**（組成見表後）。是哪一章沒收錄，看同一列的 `chapter_code`；章名看 `GET /work-items` 裡同一個 `work_item_id` 的 `spec_chapter` |
| `NEEDS_CONFIRMATION` | 沒有確定的依據可給，三種情況：沒有計價代碼（515 筆）；有代碼，但章碼既不在本案規範書、也不是施工綱要規範的任何一章（各機關自訂或舊版編號，沒有任何依據說規範書「應該有」它，74 筆）；章節在本案規範書裡，但沒有宣告相關準則（3 筆）。實測共 592 筆（58%） |

三者相加等於 `total`（248 + 188 + 592 = 1028）。`NEEDS_CONFIRMATION` 佔多數是「只給確定的
依據」的直接後果，不是缺陷：沒有計價代碼的工項查不到章節，硬填就是造假。

**`SPEC_NOT_INCLUDED` 要分流：這 188 筆是「請人判斷的候選」，不是 188 個漏洞。** 實測它們
分屬 26 章，組成很不平均：單一最大的是 `01271` 計量與計價，**83 筆，佔 44%**；其次是
`13706` 門禁管制設備 21 筆、`02891` 標誌 11 筆、`01450` 品質管理 10 筆、`10801` 浴廁附屬配件
9 筆、`13100` 避雷設備 9 筆，其餘 20 章合計 45 筆。計量與計價、品質管理是行政、管理性質的章，
施工規範本來就可能不收，不一定是漏收（這兩章合計 93 筆，佔 49%）；門禁管制設備、避雷設備
這類章對應標單裡真要施作的工項，規範書沒收錄才是實質的缺漏。系統不區分章的性質，哪一章要
追究得由人判斷；前端不要把 188 當成「規範書漏收了 188 項」，建議依章分組呈現，章碼用每一列的
`chapter_code`（這批的 `chapter` 是 `null`，只有 `chapter_code` 說得出缺的是哪一章）。

`spec_warning` 不是 null 時，代表本案規範書的解析品質不佳（大量頁面以圖為主），
依據可能殘缺——不要把檢核結果當成完整的。POST 與 GET 都會帶，使用者多半是用 GET 看檢核表。

**依據（`bases`）是引述；`verification_status` 說明它查證到什麼程度，而且只有一部分查得到。**
每一筆都是從本案規範書該章「相關準則」那一段抽出來的名稱，原樣存下。`POST` 建檢核表時，
會把其中**非標準**的名稱拿去全國法規索引（`data/taiwan_law_index.json`，11,793 筆，只含
法律與法規命令）查，結果存在資料庫；`GET` 只讀，不重查。

| `verification_status` | 意義 |
|---|---|
| `ACTIVE` | 在索引裡找到**完全同名**的法規，現行有效 |
| `AMENDED` | 找到完全同名，但**修正條文已公布、生效日在未來**：現在有一個版本落差，引用時要確認適用哪一版。不是「曾經修正過」——幾乎每部法規都修正過 |
| `REPEALED` | 找到完全同名，官方標示已廢止 |
| `null` | **未查證**。系統對這個名稱不做任何宣稱 |

實測只出現過 `ACTIVE` 與 `AMENDED`。這個欄位**永遠不會是 `NOT_FOUND`**：查不到就是 `null`，
不存「查無此法規」。

**狀態是 `POST` 當下的快照，`GET` 不會更新它。** `AMENDED` 是拿「今天」和索引裡的生效日比出來的：
生效日**晚於**今天才是 `AMENDED`，所以到了生效日**當天**就變 `ACTIVE`，不是之後。
實測有三個**名稱**是 `AMENDED`，合計 27 **筆**依據（就是下方覆蓋率表的 27）：職業安全衛生
教育訓練規則（12 筆）與職業安全衛生設施規則（12 筆），生效日都是 2027-01-01；廢棄物清理法
（3 筆），生效日 2028-07-15。所以職業安全衛生設施規則要到 2027-01-01 當天或之後再 `POST`
一次，才會變成 `ACTIVE`；在那之前 `GET` 讀到的一直是 `AMENDED`。

以下是第 01574 章這一列 `bases` 的**節錄**——該章共 8 筆依據，這裡只挑 2 筆，其餘 6 筆省略：

```json
"bases": [
  { "basis_type": "law", "reference": "職業安全衛生法", "detail": "第01574章 相關準則",
    "verification_status": "ACTIVE" },
  { "basis_type": "regulation", "reference": "職業安全衛生設施規則", "detail": "第01574章 相關準則",
    "verification_status": "AMENDED" }
  // …其餘 6 筆省略
]
```

**只採完全同名，模糊比對刻意不用。** 模糊比對會給出「有信心的錯」：拿
「低電壓金屬閉鎖型配電箱檢驗法」（一個 CNS 試驗方法的名稱，因為結尾是「法」被抽取器判成
`law`）去索引搜尋，最像的三個候選是商品檢驗法、**民法**、醫事檢驗師法。採用其中任何一個，
就是在這筆依據上填一個看起來有根據、其實是錯的狀態——而且因為欄位填滿了，比留白更難被發現。
所以寧可留 `null`。

**`null` 是未查證，不是「查無此法規」。** 下面這些情況都會是 `null`：

1. **標準**（`basis_type` 是 `standard`：CNS／ASTM／ISO／JIS 等）。沒有任何資料來源可查，
   根本沒有送查。
2. **非標準，但索引裡找不到完全同名**，原因有四種（前兩種說的是真的法規，只是名稱對不上索引）：
   - **規範書引用的是已更名的舊名稱：屋內線路裝置規則（實測 129 筆依據）。** 這部法規在
     2018-07-17 經經濟部令更名為**用戶用電設備裝置規則**（全國法規資料庫該法規沿革第 19 筆：
     「原名稱：屋內線路裝置規則；新名稱：用戶用電設備裝置規則」）。索引裡只有新名稱
     （`J0030018`），沒有任何一筆名稱含「屋內線路」，所以舊名稱查不到。**這就是本節覆蓋率
     表裡那 97 筆 `ACTIVE` 的用戶用電設備裝置規則——同一部法規的新舊兩個名稱。**
     第 16401 章把新舊名稱並列（同樣那 97 個工項各有兩筆），第 16061、16742、16782 章只寫
     舊名稱。所以這 129 筆是 `null`，原因出在**本案規範書引用了一個已經更名的名稱**：這是
     對規範書的一項檢查發現，不是資料來源缺資料。
   - **建築技術規則（17 筆）。** 它也是真的法規，只是索引不以這個名稱登錄，而是拆成四編
     （建築技術規則建築構造編、建築設備編、建築設計施工編、總則編）。
   - **索引沒有收這一類。** 索引不含行政規則、作業要點與工程規範，所以 `engineering_spec` 與
     `announcement` 兩類（實測合計 67 筆）一筆也查不到。
   - **抽取器抽出來的名稱本身是殘缺或拼湊的**，不是任何法規的名稱。實測有「檢查辦法」（12 筆）、
     「令規章和技術規則」（4 筆）、「經濟部最新修訂屋內線路裝置規則」（6 筆）。這些
     維持 `null` 是對的。
3. **建檔當下索引讀不到。** 索引檔不存在、或不是合法的 JSON：查證整批跳過、全部維持 `null`，
   `POST` 照樣回 201、檢核表照樣產出；索引補齊後重跑 `POST` 才會補上。（JSON 合法、但內容的
   形狀不對要分兩種。最外層是陣列、`regulations` 是 `null` 或物件、或條目缺 `name` 或
   `external_id`，會讓這次 `POST` 整個失敗，回 500，不會悄悄變成 `null`。但**缺 `regulations`
   這個鍵**不會：索引被讀成空的，查證整批靜默地全部是 `null`，`POST` 照樣回 201，和索引
   缺檔是同樣的結果。）
4. **遷移 `0005`（加 `verification_status` 欄）之前建好的依據。** 這些列的欄位是 `null`，
   要重跑 `POST` 才會有值；`GET` 不補查。

前端不要把 `null` 顯示成「查無此法規」「不存在」或警示，也不要顯示成「已查證」；它就是「沒有
這項資訊」。`ACTIVE`／`AMENDED`／`REPEALED` 只說明**索引裡有這個名稱**以及它的狀態，不說明
`basis_type` 判得對不對。

**實測覆蓋率（2026-10-16，真實標單與規範書）**：1028 個工項的檢核表共 2846 筆依據，其中標準 2054 筆
（不送查）、非標準 792 筆（`law` 374、`regulation` 351、`engineering_spec` 58、
`announcement` 9），792 筆只有 96 個相異名稱。

| | 數量 | 佔 2846 筆依據 |
|---|---|---|
| 查到完全同名（`ACTIVE` 159、`AMENDED` 27） | **186 筆**（13 個名稱，佔 96 個相異名稱的 13.5%；佔 792 筆非標準的 23.5%） | **6.5%** |
| `null` 未查證 | 2660 筆 | 93.5% |

也就是說，**絕大多數依據的 `verification_status` 是 `null`**，這是這個查證方式的正常結果，不是
錯誤：2660 筆 `null` 裡有 2054 筆是標準，另外 606 筆非標準沒查到同名（`law` 326、`regulation`
213、`engineering_spec` 58、`announcement` 9）。覆蓋率集中在少數名稱：用戶用電設備裝置規則
一個名稱就佔 97 筆，超過那 186 筆的一半——而它的舊名稱屋內線路裝置規則（上面第 2 點）另有
129 筆停在 `null`。這個數字是把 `data/app.db` 既有的依據名稱，用建檢核表
同一個查證函式（`verify_names`）重查全國法規索引量到的；該資料庫當時還沒套用
`work_item_bases.verification_status` 欄位的遷移，所以不是從欄位讀出來的。

`basis_type` 是抽取器依名稱判的類別（`RegulationType` 的值，實測有 `law`、`regulation`、
`standard`、`engineering_spec`、`announcement`），可以用來分類顯示，但它**不是查證結果（查證看
`verification_status`），而且會誤判**：抽取器只看名稱的結尾，而且字尾表（`backend/app/extractors/rule_engine.py`
的 `_SUFFIX_TYPES`）有先後順序：以「辦法」「細則」「規則」「準則」結尾的是 `regulation`
（「辦法」也以「法」結尾，但字尾表先比到它；實測以「辦法」結尾的 5 個相異名稱全是
`regulation`），以「標準」結尾的是 `standard`，以「條例」結尾、或沒被前面任何字尾接走而以
「法」結尾的才是 `law`；CNS／ASTM／ISO／JIS 等編號樣式也判為 `standard`。實測 `law` 依據的
73 個相異名稱裡，只有 8 個是法律（職業安全衛生法、噪音管制法……），其餘 65 個多半是 CNS 試驗
方法的名稱（鋸切長條試體取樣法、瀝青物針入度試驗法……）；反過來，「各類場所消防安全設備設置
標準」是法規命令，卻因為結尾是「標準」被判成 `standard`。所以 `law` 不等於「已確認是法律」。

`detail` 是出處，只寫到章（`第09912章 相關準則`）。不寫小節號：相關準則通常編在 1.4，但
實測有 4 章（01523、01574、02786、03110）編在 1.3，系統不宣稱它不知道的小節號——不要從
`detail` 解析小節號。`chapter.version` 是規範書頁首寫的版本，不含「V」字首（頁首的 `V3.0`
在這裡是 `3.0`）。

契約依據是專案層級的，不逐工項列（`contract_note`）：工項名稱比對契約的表面
命中率 61%，但其中 93% 來自「產品」「施工費」這兩個通用前綴。

**耗時與大小**（在一台 Windows 機器上實測，本機 SQLite；真實標單 1028 個工項、
規範書 772 頁；用 `127.0.0.1` 呼叫，原因見下）：回應 531,237 bytes（約 519 KiB），不分頁。

耗時**在同一台機器上就跳得很厲害**，四次獨立量測（2026-10-07 至 10-08，合計 POST 40 次、
GET 66 次）的全距是：

| | 全距 | 各次量測的中位數 |
|---|---|---|
| `POST` | 1.98 至 4.56 秒 | 2.0、2.2、3.7、4.0 |
| `GET` | 0.05 至 0.35 秒 | 0.10、0.13、0.21、0.27 |

**不要引用其中任何一個單次數字當成基準。** 本文件一度寫「POST 約 2.0 秒（1.98 至 2.02）」，
那是機器安靜時的地板被當成範圍寫；重測時有三成的請求超過 3.7 秒。差異來自機器負載，
不是資料量——量測時資料庫裡沒有任何孤兒列。

結論不受影響：即使最慢的 4.56 秒，也遠低於會讓人想加分頁的量級。
量測用的那台機器上，用 `localhost` 呼叫每個請求都多出約 2 秒：`localhost` 先解析成 IPv6
`::1`，而 uvicorn 預設只聽 `127.0.0.1`，連 `::1` 被拒絕之後才退回 IPv4（連 `GET /api/health`
也是 2.1 秒）。那是連線延遲，不是 API 的耗時；其他機器或其他網路設定不一定這樣。量測請用
`127.0.0.1`，才量得到伺服器本身。

已知限制：要判斷「本案規範未收錄」得查施工綱要規範目錄（`data/pcces_index.json`），但只有走到
那一步的請求才會讀它。目錄不存在時（還沒跑過 `python scripts/sync_pcces.py`）：POST，而且有
工項的章碼不在本案規範書裡，是 500 `INTERNAL_ERROR`（這時沒有任何東西被寫入，上一次建好的原封
不動）；GET，而且這個專案已經 POST 成功過、有章節索引，也是 500。從沒 POST 成功過的專案 GET
仍然是 200（索引是空的，用不到目錄）；沒掛規範書、或所有工項的章碼都在規範書裡的專案，POST 與
GET 都用不到目錄。500 的原因只寫在伺服器 log 裡。

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
