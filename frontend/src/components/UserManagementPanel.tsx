import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "../api/client";
import type { ManagedUser } from "../api/types";

export function UserManagementPanel() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
      await api.createUser(username, password);
      setUsername("");
      setPassword("");
      setNotice("使用者已建立；對方首次登入時需要變更密碼。");
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

  return (
    <div className="user-management">
      <section className="card">
        <h2>新增一般成員</h2>
        <p className="hint">初始密碼至少 12 個字元，成員首次登入時必須更改。</p>
        <form className="user-create-form" onSubmit={createUser}>
          <label>登入名稱<input required maxLength={128} value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>初始密碼<input type="password" required minLength={12} maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <button type="submit">建立成員</button>
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
              {user.is_active && user.role !== "tenant_admin" && <button type="button" className="secondary" onClick={() => void deactivate(user)}>停用</button>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
