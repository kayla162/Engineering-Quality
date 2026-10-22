# 本機登入與租戶資料隔離 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加入本機帳密登入、租戶管理員／成員角色、可撤銷的 Cookie session，並確保所有業務 API 僅能存取登入者所屬租戶資料。

**Architecture:** 使用 `tenants`、`users`、`sessions` 資料表；session cookie 保存隨機 secret，資料庫只保存 secret hash。FastAPI 解析 session 成 `CurrentUser` 並注入 service，所有 repository 以 tenant_id 過濾根資源，衍生資源先驗證所屬文件或專案。前端統一透過 API client 附帶 Cookie，並提供登入、登出、首次改密碼和管理員帳號管理。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、Pydantic v2、React 18、TypeScript、Argon2id password hash、opaque database-backed sessions。

**Spec:** `docs/superpowers/specs/2026-10-21-local-auth-and-tenant-isolation-design.md`

**Execution status:** Implemented in the isolated worktree. Static Python syntax, `git diff --check`, frontend production build, and Alembic revision-chain inspection passed; revision `0006` is head after `0005`. Code review found and the implementation now handles concurrent duplicate usernames as HTTP 409. Tests and database migrations were not run per task constraints. The login throttle is process-local, as scoped for this first version; multi-worker deployments should use a shared limiter.

## Global Constraints

- 密碼雜湊採 Argon2id 或同等現代方案；永不保存或記錄明文密碼。
- session secret 只以 hash 存入資料庫；cookie 使用 HttpOnly、SameSite=Lax，生產環境 Secure。
- 未登入的受保護 API 回傳 401；跨租戶資源一律以與不存在資源相同的 404 回應。
- 租戶 ID 一律由登入 session 推導，不能由客戶端參數指定。
- 健康檢查與來源就緒狀態可匿名讀取；使用者管理端點限 tenant_admin。
- 首位租戶管理員由互動式部署命令建立，不在 migration 中放入預設密碼。
- 既有 NULL tenant_id 的文件、專案與法規資料歸入預設租戶。
- 文件雜湊唯一性改為租戶範圍 `(tenant_id, file_hash)`。
- 不做 OAuth/OIDC、公開註冊、邀請郵件、MFA、跨租戶共享目錄或細粒度角色。
- 本次不新增或執行測試；依當前工作要求，測試需由使用者另行要求。

---

## File Structure and Responsibilities

### Backend identity and persistence

- Create `backend/app/models/tenant.py`: tenant row and relationships.
- Create `backend/app/models/user.py`: user identity, role, activation and first-login password-change state.
- Create `backend/app/models/session.py`: hashed opaque session secrets, expiry and revocation.
- Modify `backend/app/models/__init__.py`: register new models for metadata and migrations.
- Modify `backend/app/models/document.py`: remove global file-hash uniqueness from the column and use a tenant/hash composite unique constraint.
- Create `migrations/versions/0006_auth_tenants_sessions.py`: create identity tables, seed the default tenant, backfill existing tenant roots, and update file uniqueness.
- Modify `requirements.txt`: add a maintained Argon2 password hashing package.
- Modify `backend/app/core/config.py` and `.env.example`: session expiry and cookie security settings, configured origins, and login throttling values.

### Backend authentication and authorization

- Create `backend/app/services/auth_service.py`: hash/verify password, create/resolve/revoke sessions, change password and provision tenant users.
- Create `backend/app/api/routes/auth.py`: login, logout, current-user and password-change endpoints.
- Create `backend/app/api/routes/users.py`: tenant-admin list/create/update(deactivate) users.
- Create `backend/app/schemas/auth.py` and `backend/app/schemas/user.py`: validated request and response contracts without password hashes or session secrets.
- Modify `backend/app/core/security.py`: `CurrentUser`, required-user and required-admin dependencies, secure cookie helpers, Origin checks for unsafe requests and login throttling.
- Modify `backend/app/api/deps.py`: inject current user into tenant-aware services.
- Modify `backend/app/api/router.py`: mount identity routes and preserve anonymous health/sources routes.
- Modify `backend/app/main.py`: include authentication and session behavior in application setup where middleware configuration belongs.

### Tenant-scoped business data

- Modify `backend/app/repositories/documents.py`, `projects.py`, `jobs.py`, `references.py`, `regulations.py`, `checklist.py`: require tenant scope for root queries and mutations; derive child access from tenant-owned document/project/regulation records.
- Modify `backend/app/services/document_service.py`, `project_service.py`, `job_service.py`, `reference_service.py`, `regulation_service.py`, `matching_service.py`, `report_service.py`, `checklist_service.py`, `analysis_service.py`: accept a trusted tenant ID and pass it to repository operations; remove fixed tenant authorization from request paths.
- Modify business routes under `backend/app/api/routes/`: require identity for documents, projects, jobs, references, regulations, reports and checklist; avoid disclosing cross-tenant existence.
- Modify `backend/app/jobs/background_runner.py`: resolve tenant ownership through the document row when background work starts; never depend on request context.

### Frontend and operational setup

- Modify `frontend/src/api/client.ts`: include credentials, expose auth/user APIs, and normalize 401 handling.
- Modify `frontend/src/api/types.ts`: add session user and user-management response types.
- Create `frontend/src/pages/LoginPage.tsx`, `ChangePasswordPage.tsx` and `UsersPage.tsx`: login, forced password change, and tenant-admin user management.
- Modify `frontend/src/App.tsx`: load `/auth/me`, gate business UI, show account/logout controls, and route first-login users to password change.
- Modify `frontend/src/styles.css`: style the new identity screens using existing visual conventions.
- Create `scripts/create_admin.py`: prompt for tenant and admin identity/password without command-line password arguments or logging secrets.
- Modify `README.md`, `docs/api.md`, `docs/database.md` and `.env.example`: explain first-admin setup, auth endpoints, tenant behavior and cookie settings.

## Implementation Tasks

### Task 1: Add tenant, user and session persistence

**Files:**
- Create: `backend/app/models/tenant.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/session.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/project.py`
- Modify: `backend/app/models/regulation.py`
- Create: `migrations/versions/0006_auth_tenants_sessions.py`
- Modify: `requirements.txt`

**Interfaces:**
- `Tenant.id`, `Tenant.name`, `Tenant.is_active`, `Tenant.created_at`.
- `User.id`, `User.tenant_id`, `User.username`, `User.password_hash`, `User.role`, `User.is_active`, `User.must_change_password`.
- `AuthSession.id`, `AuthSession.user_id`, `AuthSession.secret_hash`, `AuthSession.created_at`, `AuthSession.expires_at`, `AuthSession.revoked_at`.

- [x] Define SQLAlchemy models using existing `uuid_pk()` and `created_at_column()` conventions; username uniqueness is global and tenant names are not treated as an authentication secret.
- [x] Register the models in `models/__init__.py` so Alembic metadata sees them.
- [x] Change the Document model from global `file_hash` uniqueness to a named `(tenant_id, file_hash)` unique constraint and retain the tenant index.
- [x] Make document, project and regulation tenant IDs required foreign keys to `tenants.id` so root rows cannot reference missing tenants.
- [x] Write migration `0006` after `0005_basis_verification_status`; create the default tenant with `settings.DEFAULT_TENANT_ID`, backfill NULL tenant IDs in documents/projects/regulations, create user/session tables, and replace the global file hash constraint with the composite constraint.
- [x] Add the Argon2 password hashing dependency to `requirements.txt`.
- [x] Inspect migration upgrade/downgrade paths for both SQLite and PostgreSQL batch-alter behavior; do not run migration commands unless separately requested.

### Task 2: Implement authentication service and session dependencies

**Files:**
- Create: `backend/app/services/auth_service.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `backend/app/api/deps.py`

**Interfaces:**
- `CurrentUser`: immutable value with `id: UUID`, `tenant_id: UUID`, `username: str`, `role: str`, `must_change_password: bool`.
- `AuthService.authenticate(username: str, password: str) -> tuple[User, AuthSession] | None`.
- `AuthService.create_session(user: User) -> tuple[str, AuthSession]`, returning raw secret only for setting the cookie.
- `AuthService.resolve_session(raw_secret: str) -> CurrentUser | None`.
- `AuthService.revoke_session(raw_secret: str) -> None`.
- `AuthService.change_password(user_id: UUID, old_password: str, new_password: str) -> None`.
- `get_current_user(request, session) -> CurrentUser | None`; `require_current_user(...) -> CurrentUser`; `require_tenant_admin(...) -> CurrentUser`.

- [x] Add settings for cookie name, session TTL, Secure flag and allowed browser origins; keep secret values environment-only.
- [x] Implement password hash/verify with Argon2id and a fixed dummy hash verification for unknown usernames to reduce timing differences.
- [x] Generate cryptographically random session secrets; persist SHA-256 hashes only; enforce expiry and revoked state when resolving sessions.
- [x] Revoke every active session on password change or account deactivation; revoke only the presented session on logout.
- [x] Add an in-process login attempt limiter keyed by normalized username and client IP with a bounded time window and bounded memory; return the same 401 body for unknown, disabled and incorrect-password accounts.
- [x] Validate Origin on unsafe cookie-authenticated requests against configured `CORS_ORIGINS`; reject absent or unapproved browser origins for those requests.
- [x] Add FastAPI dependencies that return 401 for unauthenticated business requests and 403 for non-admin user-management requests.

### Task 3: Add auth and tenant user APIs

**Files:**
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/schemas/user.py`
- Create: `backend/app/api/routes/auth.py`
- Create: `backend/app/api/routes/users.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- `POST /api/auth/login` accepts `{username, password}` and sets the HttpOnly session cookie; response includes user summary and `must_change_password`.
- `POST /api/auth/logout` revokes current session and expires the cookie.
- `GET /api/auth/me` returns `{user_id, username, role, tenant_id, tenant_name, must_change_password}`.
- `POST /api/auth/change-password` accepts `{old_password, new_password}`, revokes every session including the current session, and clears the cookie; require old password unless `must_change_password` is true.
- `GET /api/users`, `POST /api/users`, `PATCH /api/users/{user_id}` are tenant-admin-only and never return hashes/secrets.

- [x] Add Pydantic request models that reject empty usernames, weak initial/new passwords and attempts to submit `tenant_id` or privileged role from ordinary clients.
- [x] Add login/logout/me/password-change handlers using database dependency and AuthService; use explicit cookie parameters for HttpOnly, SameSite=Lax, Secure and Max-Age.
- [x] Add tenant-admin user list/create/deactivate handlers; always use the administrator's tenant ID, prohibit self-deactivation and prohibit disabling the tenant's last active admin.
- [x] Mount auth/user routers; retain `/api/health` and `/api/sources` as anonymous endpoints and place authentication on all business routers.
- [x] Ensure a user with `must_change_password=true` can reach only `/auth/me`, `/auth/logout`, and `/auth/change-password` until the password is changed.

### Task 4: Scope documents, projects and analysis jobs by tenant

**Files:**
- Modify: `backend/app/repositories/documents.py`
- Modify: `backend/app/repositories/projects.py`
- Modify: `backend/app/repositories/jobs.py`
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/services/project_service.py`
- Modify: `backend/app/services/job_service.py`
- Modify: `backend/app/jobs/background_runner.py`
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/app/api/routes/projects.py`
- Modify: `backend/app/api/routes/jobs.py`

**Interfaces:**
- Root repository methods that retrieve or mutate a document/project/job require `tenant_id: UUID` and return `None` for records outside that tenant.
- `DocumentService(session, tenant_id)` and `ProjectService(session, tenant_id)` are request-scoped to a trusted `CurrentUser.tenant_id`.
- Jobs are authorized through their owning document; background processing resolves the tenant from that document.

- [x] Add tenant predicates to document get/list/hash lookup and project get/list methods; constrain file-hash duplicate detection by tenant.
- [x] Add tenant predicates to create/update/link operations; reject attaching documents from another tenant using the same 404 behavior as missing IDs.
- [x] Pass the authenticated tenant ID through document and project route dependencies into their services; remove request-path use of the fixed default tenant ID.
- [x] Scope job status and analysis start by the owning document's tenant before returning job data or enqueueing work.
- [x] Make background analysis resolve document ownership from the database and pass its tenant to all analysis services.

### Task 5: Scope references, regulations, checklists and reports

**Files:**
- Modify: `backend/app/repositories/references.py`
- Modify: `backend/app/repositories/regulations.py`
- Modify: `backend/app/repositories/checklist.py`
- Modify: `backend/app/services/reference_service.py`
- Modify: `backend/app/services/regulation_service.py`
- Modify: `backend/app/services/matching_service.py`
- Modify: `backend/app/services/report_service.py`
- Modify: `backend/app/services/checklist_service.py`
- Modify: `backend/app/services/analysis_service.py`
- Modify: `backend/app/api/routes/references.py`
- Modify: `backend/app/api/routes/regulations.py`
- Modify: `backend/app/api/routes/reports.py`
- Modify: `backend/app/api/routes/checklist.py`

**Interfaces:**
- Each business service receives trusted tenant ID at construction or method invocation.
- A reference is authorized by its document's tenant; a checklist item is authorized by its project's tenant; a regulation row is authorized by its own tenant.
- `regulations.search/get/upsert` require tenant ID and use tenant-scoped reads/writes.

- [x] Add tenant-scoped regulation search/get/upsert and ensure source results are persisted to the active tenant rather than `DEFAULT_TENANT_ID`.
- [x] Authorize references and review updates by joining through the reference's document; never fetch a child row by UUID alone.
- [x] Authorize checklist chapter/basis replacement and reads by project tenant before touching derived rows.
- [x] Authorize report retrieval/export by document tenant before loading any report sections or file paths.
- [x] Pass tenant identity from API dependency to all affected services and update analysis/matching call chains to preserve that identity.
- [x] Keep external source readiness anonymous and ensure authentication failures happen before external source calls or file reads.

### Task 6: Add secure initial-admin provisioning

**Files:**
- Create: `scripts/create_admin.py`
- Modify: `README.md`
- Modify: `docker-compose.yml`

**Interfaces:**
- `python scripts/create_admin.py` prompts for tenant name, admin username and password using hidden password input; the first invocation names and uses the migration-created default tenant, and later invocations create a new tenant and its first active `tenant_admin` transactionally.
- Re-running the command with a tenant name that already has an active admin refuses to create a second bootstrap admin and directs the operator to the admin user API.

- [x] Build the CLI using existing settings/database session conventions; never accept password as a command-line argument or print it.
- [x] Reuse the seeded default tenant, set its display name and create the first admin; lock the tenant row and refuse bootstrap when an active admin already exists.
- [x] Document first-run migration and admin creation order in README; explain that no seeded credentials exist.
- [x] Keep startup independent of bootstrap state so containers can start before an operator creates the first admin.

### Task 7: Add frontend login, session and user management flows

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/ChangePasswordPage.tsx`
- Create: `frontend/src/pages/UsersPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `api.login(username, password)`, `api.logout()`, `api.getCurrentUser()`, `api.changePassword(oldPassword, newPassword)`, `api.listUsers()`, `api.createUser(username, initialPassword)` and `api.deactivateUser(userId)`.
- All API requests use `credentials: "include"`; no password/session data is written to localStorage or sessionStorage.

- [x] Add session user and tenant user response types matching backend schemas.
- [x] Set `credentials: "same-origin"` centrally in the API client and add auth methods; handle 401 by clearing in-memory user state.
- [x] Gate the existing document/project UI behind `/auth/me`; render LoginPage when no session exists.
- [x] Show account identity and logout; route `must_change_password` users to ChangePasswordPage and block navigation to business UI until completion.
- [x] Show UsersPage only for `tenant_admin`; create users with a temporary password and provide an explicit deactivate action.
- [x] Style new screens in the existing stylesheet without introducing a component framework.

### Task 8: Update API/database documentation and self-review implementation

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/database.md`
- Modify: `README.md`
- Modify: `.env.example`

- [x] Document auth and user endpoints, cookie behavior, 401/403/404 semantics, bootstrap command, required environment settings and migration behavior.
- [x] Remove stale claims that the app has no login mechanism or that tenant IDs are unused defaults.
- [x] Review each business route and repository against the spec's tenant-root list, especially report exports, background jobs and reference review mutations.
- [x] Inspect the final diff for secrets, unscoped UUID lookups, unrestricted user-admin operations, stale default-tenant writes and accidental test changes.

## Self-Review

- Spec sections 1–3 are covered by Tasks 1, 2 and 6.
- Spec sections 4 and 7 are covered by Tasks 2 and 3.
- Spec section 5 is covered by Tasks 4 and 5.
- Spec section 6 is covered by Task 1 and Task 6.
- Spec section 8 is covered by Task 7.
- Spec section 9's expected behavior is represented in the implementation interfaces and final review checklist; automated tests are intentionally excluded by the current instruction not to add or run tests unless requested.
- Spec section 10 is kept out of all tasks.
- Placeholder scan: no TODO/TBD implementation steps are used.
- Interface names are consistent between task dependencies: `CurrentUser`, `AuthService`, tenant-scoped services and frontend `api.*` auth methods.
