# 本機登入與租戶資料隔離設計

日期：2026-10-21  
狀態：設計草案，待使用者審閱  
範圍：第一階段企業使用基礎

## 1. 目標

為目前單機 MVP 加入本機帳號登入、租戶管理員與一般成員兩種角色，並確保 API 只能讀寫目前登入者所屬租戶的業務資料。部署時建立第一個租戶和管理員；不提供公開註冊，不依賴外部身份提供者或郵件服務。

## 2. 現況

- `backend/app/core/security.py` 的 `get_current_user()` 目前永遠回傳 `None`。
- `documents`、`projects`、`regulations` 已有可為 NULL 的 `tenant_id`，但 repository 與 API 尚未依登入租戶過濾資料。
- `DocumentService` 與法規服務目前使用固定的 `DEFAULT_TENANT_ID`。
- API 由 `backend/app/api/router.py` 集中掛載；服務由 `backend/app/api/deps.py` 建立。
- 專案、文件及其衍生工項、章節、依據、工作和引用可沿外鍵關聯到各自的租戶根資料。
- `documents.file_hash` 目前全域唯一。若開始多租戶，重複上傳檢查必須避免揭露另一租戶是否擁有相同檔案。

## 3. 使用者與角色

### 租戶

建立 `tenants` 資料表，至少包含 UUID、名稱、建立時間和啟用狀態。每位使用者屬於一個租戶。登入者不可透過請求參數指定或切換租戶。

### 使用者

建立 `users` 資料表，至少包含 UUID、tenant_id、唯一登入名稱、password_hash、role、is_active、must_change_password、created_at 與 updated_at。角色限 `tenant_admin` 和 `member`。

- 部署管理命令以互動方式建立首個租戶管理員，密碼不經命令列參數或 log 傳遞。
- 租戶管理員可建立及停用同租戶使用者；新使用者由管理員設定初始密碼，第一次成功登入後必須更改。
- 一般成員可使用現有專案、文件、分析、檢核、覆核及報表功能，但不能管理使用者。
- 不提供自助註冊、跨租戶使用者管理、密碼重設郵件或多因素驗證。

### 密碼

使用 Argon2id 或同等現代密碼雜湊方案保存密碼；不保存或記錄明文密碼。登入失敗使用統一錯誤訊息，並對登入端點加上基本速率限制。

## 4. 工作階段與 API

採用資料庫保存、可撤銷的 opaque session。瀏覽器只持有隨機 session secret 的 `HttpOnly` Cookie；資料庫只保存其雜湊、user_id、建立時間、到期時間及撤銷／輪替狀態。密碼更新及帳號停用時撤銷該使用者所有 session；登出撤銷當前 session。

Cookie 使用 `SameSite=Lax`，正式環境設 `Secure`，開發環境可由設定關閉；同時驗證寫入請求的 Origin 或使用 CSRF token。所有含憑證的跨來源請求只允許明確設定的 CORS origins。

新增端點：

- `POST /api/auth/login`：驗證登入名稱與密碼，建立 session；首次登入需改密碼。
- `POST /api/auth/logout`：撤銷當前 session。
- `GET /api/auth/me`：回傳目前使用者、角色與租戶基本資訊。
- `POST /api/auth/change-password`：變更密碼並撤銷其他 session。
- `GET /api/users`、`POST /api/users`、`PATCH /api/users/{id}`：租戶管理員管理同租戶帳號；不得透過此 API 跨租戶建立管理員。

健康檢查與來源就緒狀態端點可維持匿名讀取；所有文件、專案、分析、檢核、法規引用及報表 API 均需登入。管理使用者的端點另需 `tenant_admin`。

## 5. 租戶範圍

從 session 解析不可由客戶端修改的 `CurrentUser(id, tenant_id, role)`，經 FastAPI dependency 注入服務層。Repository 查詢需將租戶條件與資源識別條件合併；不存在與不屬於租戶的資源均回傳相同的 404，避免 IDOR 洩漏。

所有根資源都要執行租戶檢查：文件、專案、法規紀錄及工作。衍生資料（段落、分析工作、引用、工項、章節索引、依據、覆核及報表）必須透過所屬根資源確認租戶後才讀寫。背景工作啟動時沿文件關聯取得租戶，不能依賴 HTTP request-local 身分。

不得以 `DEFAULT_TENANT_ID` 作為已登入請求的授權來源。新資料使用 `CurrentUser.tenant_id`。本階段法規目錄仍依資料列的 tenant_id 隔離，不建立跨租戶共享目錄或新增公開／企業來源的存取模型。

## 6. Migration 與既有資料

新增 tenants、users、sessions 及必要索引。Migration 建立一個預設租戶，將現有 `documents`、`projects`、`regulations` 中 NULL 的 tenant_id 歸入此租戶；既有專案衍生資料透過其 project/document 關聯繼承範圍。

將文件去重限制改為 `(tenant_id, file_hash)`，使相同檔案可以存在不同租戶，且重複上傳結果不洩漏其他租戶資訊。Migration 必須保留已存在資料，並對不符合新限制的既有索引／唯一約束做明確調整。

部署時由管理命令建立首位管理員，不在 migration 內植入預設密碼。無管理員帳號時，系統仍可啟動，但管理命令須提供安全建立帳號的方法。

## 7. 錯誤與安全行為

- 未登入的受保護 API 回傳 401。
- 登入失敗不區分不存在的使用者、錯誤密碼或停用帳號。
- 非管理員呼叫使用者管理 API 回傳 403。
- 跨租戶資源存取回傳 404，且不觸發任何檔案讀取、背景工作或外部來源查詢。
- 帳號停用立即拒絕新請求，並撤銷既有 session。
- 密碼與 session secret 不寫入 log；管理員建立使用者時也不得將密碼寫入 response/log。

## 8. 前端

新增登入畫面、目前帳號資訊、登出與首次登入更改密碼流程。API client 使用 credentials 送出 session Cookie；401 時導回登入畫面並保留安全的原始目的路徑。租戶管理員可在簡單帳號頁面新增或停用使用者、設定初始密碼。一般成員不顯示帳號管理入口。

## 9. 驗收條件

1. 未登入不能讀寫任何業務資源；健康檢查及來源狀態仍可匿名讀取。
2. 有效帳密可登入、取得目前使用者資訊、登出；登出後 session 不能再使用。
3. 首次登入必須更改初始密碼；停用帳號及更改密碼會撤銷 session。
4. 管理員只能管理自己的租戶使用者；一般成員不能呼叫管理 API。
5. 兩個租戶的使用者無法讀取、更新、刪除或觸發另一租戶的專案、文件、工作、工項、檢核表、引用與報表；無法從錯誤回應推斷其資源是否存在。
6. 同一檔案可由不同租戶上傳，而租戶內重複上傳仍可辨識。
7. Migration 後既有資料屬於預設租戶；建立首位管理員後能正常使用現有功能。
8. 前端完成登入、登出、首次改密碼與管理員新增／停用帳號流程。

## 10. 不在本階段

OAuth／OIDC、公開註冊、邀請郵件、MFA、密碼重設郵件、細粒度角色、跨租戶共享法規目錄、全域稽核 log、OCR、RAG、法規異動監控及 Dashboard。
