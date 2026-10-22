import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedUser } from "../api/types";

export function UserManagementPanel() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<ManagedUser["role"]>("member");
  const [reactivationPasswords, setReactivationPasswords] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setUsers((await api.listUsers()).items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法載入使用者清單");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function createUser(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await api.createUser(username, password, role);
      setUsername("");
      setPassword("");
      setRole("member");
      setNotice(`${role === "tenant_admin" ? "管理員" : "一般成員"}已建立；對方首次登入時需要變更密碼。`);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法建立使用者");
    }
  }

  async function deactivate(user: ManagedUser) {
    if (!window.confirm(`確定停用 ${user.username}？`)) return;
    setError(null);
    try {
      await api.deactivateUser(user.user_id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法停用使用者");
    }
  }

  async function reactivate(user: ManagedUser, event: FormEvent) {
    event.preventDefault();
    const initialPassword = reactivationPasswords[user.user_id] ?? "";
    if (!window.confirm(`重新啟用 ${user.username}？帳號會改用新的初始密碼。`)) return;
    setError(null);
    setNotice(null);
    try {
      await api.reactivateUser(user.user_id, initialPassword);
      setReactivationPasswords((current) => ({ ...current, [user.user_id]: "" }));
      setNotice(`已重新啟用 ${user.username}；請將新初始密碼交給使用者。`);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "無法重新啟用使用者");
    }
  }

  return (
    <div className="user-management">
      <section className="card">
        <h2>新增使用者</h2>
        <p className="hint">初始密碼至少 12 個字元；新使用者首次登入時必須更改。</p>
        <form className="user-create-form" onSubmit={createUser}>
          <label>登入名稱<input required maxLength={128} value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>初始密碼<input type="password" required minLength={12} maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <label>角色<select value={role} onChange={(e) => setRole(e.target.value as ManagedUser["role"])}><option value="member">一般成員</option><option value="tenant_admin">租戶管理員</option></select></label>
          <button type="submit">建立使用者</button>
        </form>
        {notice && <p className="success">{notice}</p>}
        {error && <p className="error">{error}</p>}
      </section>
      <section className="card">
        <h2>租戶使用者（{users.length}）</h2>
        <ul className="managed-users">
          {users.map((user) => (
            <li key={user.user_id}>
              <span><strong>{user.username}</strong><small>{user.role === "tenant_admin" ? "管理員" : "一般成員"}{!user.is_active ? " · 已停用" : user.must_change_password ? " · 待變更初始密碼" : ""}</small></span>
              {user.is_active && user.role !== "tenant_admin" ? (
                <button type="button" className="secondary" onClick={() => void deactivate(user)}>停用</button>
              ) : !user.is_active ? (
                <form className="user-reactivate-form" onSubmit={(event) => void reactivate(user, event)}>
                  <input
                    type="password"
                    required
                    minLength={12}
                    maxLength={256}
                    aria-label={`${user.username} 的新初始密碼`}
                    placeholder="新初始密碼（至少 12 字元）"
                    value={reactivationPasswords[user.user_id] ?? ""}
                    onChange={(event) => setReactivationPasswords((current) => ({
                      ...current,
                      [user.user_id]: event.target.value,
                    }))}
                  />
                  <button type="submit">重新啟用</button>
                </form>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
