import { useState, type FormEvent } from "react";

import { ApiError, api } from "../api/client";
import type { SessionUser } from "../api/types";

export function LoginPage({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api.login(username, password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法登入，請稍後再試");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="card auth-card" onSubmit={submit}>
        <h1>工程法規符合性檢查平台</h1>
        <p className="hint">請使用管理員提供的帳號登入。</p>
        <label>
          登入名稱
          <input autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          密碼
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "登入中…" : "登入"}</button>
      </form>
    </main>
  );
}

export function ChangePasswordPage({
  user,
  onChanged,
}: {
  user: SessionUser;
  onChanged: () => void;
}) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("兩次輸入的新密碼不一致");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(user.must_change_password ? undefined : oldPassword, newPassword);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法變更密碼，請稍後再試");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="card auth-card" onSubmit={submit}>
        <h1>變更密碼</h1>
        <p className="hint">{user.must_change_password ? "這是初始密碼，請先設定新密碼才能使用平台。" : "新密碼至少 12 個字元。"}</p>
        {!user.must_change_password && (
          <label>目前密碼<input type="password" autoComplete="current-password" required value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} /></label>
        )}
        <label>新密碼<input type="password" autoComplete="new-password" minLength={12} required value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label>
        <label>確認新密碼<input type="password" autoComplete="new-password" minLength={12} required value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "儲存中…" : "儲存新密碼"}</button>
      </form>
    </main>
  );
}
