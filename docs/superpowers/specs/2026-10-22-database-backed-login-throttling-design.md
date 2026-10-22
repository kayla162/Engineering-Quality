# Database-Backed Shared Login Throttling

**Date:** 2026-10-22  
**Status:** Design approved for implementation

## Context

The login limiter in `backend/app/core/security.py` stores attempts in a process-local dictionary. Separate application workers therefore keep separate limits. The application already supports PostgreSQL for deployment and SQLite for local development; adding Redis would create a new operational dependency.

## Goals

- Share one login limit across application workers using the configured database.
- Preserve the current normalized username + client IP identity, sliding time window, attempt limit, 401 credential behavior, and 429 throttling behavior.
- Serialize concurrent attempts for the same identity so workers cannot independently pass the threshold.
- Retain only hashed identities and short-lived attempt timestamps.
- Support the existing PostgreSQL and SQLite database configurations without Redis.

## Non-Goals

- Add an IP-only or network-wide spray limit.
- Add account lockout, CAPTCHA, MFA, or new authentication responses.
- Trust forwarded client-IP headers beyond the existing request configuration.
- Change login settings or frontend/API contracts.

## Architecture

Add a small `LoginThrottleService` backed by two tables in migration `0007`:

- `auth_login_throttle_keys`: SHA-256 identity digest as primary key and `last_seen_at` for cleanup. The digest is computed from `normalize_username(username)`, a NUL separator, and `request.client.host`; raw usernames and IP addresses are not stored.
- `auth_login_attempts`: UUID, identity digest, and UTC attempt timestamp, with indexes for per-identity window counts and expiry cleanup.

An attempt reservation is inserted before Argon2 verification and committed immediately. This reserves capacity before workers can race through password verification. A rejected credential leaves the reservation in the window. A successful login clears that identity's recent attempts and creates the session in one short transaction. The lock is never held while Argon2 runs.

For PostgreSQL, an `INSERT ... ON CONFLICT DO UPDATE` against the identity row serializes updates to the same identity; a subsequent `SELECT ... FOR UPDATE` protects its count-and-reserve transaction. For SQLite, the upsert is a write transaction and SQLite serializes writers. SQLAlchemy provides dialect-specific upsert constructs for both backends. SQLite permits only one simultaneous writer, so concurrent login writes may queue; PostgreSQL remains the production concurrency target.

## Request Flow

1. Validate the login request's Origin as today.
2. Normalize the username and derive the identity digest.
3. In a short database transaction, prune up to 500 expired attempts and 500 stale keys, upsert and lock the identity row, count attempts newer than `now - AUTH_LOGIN_WINDOW_SECONDS`, and commit a reservation if below `AUTH_MAX_LOGIN_ATTEMPTS`.
4. If at the limit, commit cleanup and return the existing 429 response.
5. Verify credentials. Unknown, inactive, and incorrect-password accounts continue to return the same 401 response; their reservation remains until expiration.
6. On success, clear the identity's recent attempts, create the session, and commit.

If reservation or cleanup cannot reach the database, do not fall back to a process-local limiter; authentication already depends on the same database. Let the existing API error handling report the database failure rather than silently weakening the shared limit.

## Data Retention and Migration

Expired attempt rows and key rows are deleted in batches of at most 500 rows per table during login activity. This bounds cleanup work for each request; later logins continue draining any remaining backlog. The migration creates only transient throttle state and indexes, after revision `0006`. Downgrade drops the throttle tables; it does not affect users, sessions, or business data.

## Verification Constraints

Do not add or run test suites or execute database migrations under the current task constraints. Verify static Python syntax, inspect the Alembic revision chain, run the frontend production build and dependency audit, and run `git diff --check`. Report that runtime concurrency and migration execution remain unverified.
