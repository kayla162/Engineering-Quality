# Database-Backed Shared Login Throttling Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current isolated worktree. Do not add or run tests or execute migrations under the current task constraint.

**Goal:** Share login-attempt limits across application workers by persisting short-lived attempt state in the configured database.

**Architecture:** Add throttle key and attempt models in a new Alembic revision. A `LoginThrottleService` uses a dialect-specific atomic upsert to serialize a username/IP identity, counts reservations in the configured rolling window, and clears them after successful authentication. Expiry cleanup deletes at most 500 attempt rows and 500 stale keys per login. SQLite and PostgreSQL remain supported; no Redis service is added.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL, SQLite.

**Spec:** `docs/superpowers/specs/2026-10-22-database-backed-login-throttling-design.md`

## Global Constraints

- Keep `AUTH_MAX_LOGIN_ATTEMPTS` and `AUTH_LOGIN_WINDOW_SECONDS` unchanged.
- Keep the current HTTP behavior: 429 at the configured limit; identical 401 behavior for unknown, inactive, and incorrect-password accounts.
- Store only a SHA-256 digest of normalized username + NUL + client IP, not raw identity values.
- Never hold the per-identity database lock while Argon2 password verification runs.
- Do not fall back to process-local state if the shared database is unavailable.
- Do not add or run test suites or execute database migrations in this task.

---

## File Structure and Responsibilities

- Create `backend/app/models/login_throttle.py`: SQLAlchemy rows for identity locks and timestamped attempt reservations.
- Modify `backend/app/models/__init__.py`: register both models with metadata.
- Create `migrations/versions/0007_shared_login_throttle.py`: create/drop throttle tables and indexes after `0006`.
- Create `backend/app/services/login_throttle_service.py`: hash identity, prune expired rows, serialize and reserve attempts, and clear on successful authentication.
- Modify `backend/app/core/security.py`: remove the process-local limiter dictionary and helper functions.
- Modify `backend/app/api/routes/auth.py`: reserve using the database service before password verification; clear reservations on successful login.
- Modify `docs/api.md`, `docs/database.md`, `README.md`, and the existing auth implementation plan: describe shared persistence and migration `0007`.

## Implementation Tasks

### Task 1: Add throttle persistence and migration

**Files:**
- Create: `backend/app/models/login_throttle.py`
- Modify: `backend/app/models/__init__.py`
- Create: `migrations/versions/0007_shared_login_throttle.py`

**Interfaces:**
- `LoginThrottleKey.identity_hash: str` is the primary key; `last_seen_at` is a timezone-aware timestamp used for expiry cleanup.
- `LoginAttempt.id: UUID`, `identity_hash: str`, and `attempted_at` represent a reserved login attempt.
- Add indexes on `(identity_hash, attempted_at)`, `attempted_at`, and `last_seen_at` for bounded expiry cleanup.
- Migration `0007` follows revision `0006`; downgrade removes only throttle state.

- [x] Define SQLAlchemy models using the existing UUID and UTC timestamp conventions.
- [x] Register models in `models/__init__.py` so metadata imports see them.
- [x] Create migration `0007` with matching columns and indexes; make downgrade drop attempts before keys.
- [x] Inspect revision links to ensure `0007 -> 0006 -> 0005`.

### Task 2: Implement the shared throttle service

**Files:**
- Create: `backend/app/services/login_throttle_service.py`
- Read: `backend/app/core/config.py`, `backend/app/core/db.py`, and `backend/app/services/auth_service.py`

**Interfaces:**
- `LoginThrottleService(session: AsyncSession)`
- `async reserve(username: str, client_ip: str) -> bool`: commit cleanup and a reservation if the rolling count is below the configured maximum; otherwise commit cleanup and return `False`.
- `async clear(username: str, client_ip: str) -> None`: serialize on the same identity key and delete that identity's attempt rows; caller commits it together with session creation.

- [x] Normalize usernames with `normalize_username`, hash `normalized + "\0" + client_ip` with SHA-256, and retain no raw identity fields.
- [x] Select the SQLite or PostgreSQL `insert` construct from the active dialect; upsert the identity key to acquire its write/row lock.
- [x] In a short transaction, prune up to 500 expired attempts and 500 stale keys, upsert and lock the requested key, count timestamps newer than the configured cutoff, and reserve only if below the maximum.
- [x] Commit the reservation before returning to password verification; do not hold locks during Argon2 work.
- [x] Reacquire the same identity lock in `clear` before deleting recent attempts, so clearing is ordered against concurrent reservations.
- [x] Raise an explicit unsupported-dialect error instead of silently using local memory.

### Task 3: Integrate login flow and update operational docs

**Files:**
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/app/core/security.py`
- Modify: `docs/api.md`
- Modify: `docs/database.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-10-21-local-auth-and-tenant-isolation.md`

**Interfaces:**
- `POST /api/auth/login` retains its request/response schema and HTTP status behavior.
- `LoginThrottleService.reserve()` runs before `AuthService.authenticate()`.
- A failed authentication leaves the committed reservation. A successful authentication calls `clear()` before the existing session commit.

- [x] Replace process-local `login_allowed`, `record_login_failure`, and `clear_login_failures` calls with `LoginThrottleService` calls.
- [x] Remove `_LOGIN_FAILURES`, deque/time imports, and obsolete helpers from `security.py`.
- [x] Preserve Origin validation, credential error body, rate-limit error body, session cookie behavior, and forced password-change flow.
- [x] Document shared-database persistence, new migration requirement, short-lived hashed identifiers, and SQLite write-serialization tradeoff.
- [x] Remove the old plan note that says the limiter remains process-local; replace it with the migration/runtime verification status.

### Task 4: Static verification and review

**Files:**
- Review: the full diff and the design/spec/implementation-plan checklist.

- [x] Run Python AST parsing over backend and scripts without generating bytecode.
- [x] Inspect the Alembic revision chain and verify `0007` is the sole new head after `0006` without executing migration commands.
- [x] Run `git diff --check`.
- [x] Run frontend production build and `npm audit`; do not run any test suite.
- [x] Review auth transaction boundaries, error behavior, identity hashing, and expiry cleanup; report that live concurrency and migration execution were not verified.

---

**Review note:** No Critical or Important findings. Global expiry cleanup now deletes at most 500 attempts and 500 stale keys per login, limiting per-request cleanup work while later logins drain the backlog. Migration 0007 and live concurrency were not executed or load-tested.
