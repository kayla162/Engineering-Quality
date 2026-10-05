import { useState } from "react";

import type { Project } from "../api/types";

export function ProjectPanel({
  projects,
  selectedId,
  onSelect,
  onCreate,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (projectId: string) => void;
  onCreate: (name: string) => void;
}) {
  const [name, setName] = useState("");

  function submit() {
    // 只有空白的名稱後端會回 400，在這裡先擋掉省一趟往返
    if (name.trim() === "") return;
    onCreate(name.trim());
    setName("");
  }

  return (
    <section className="card">
      <h2>專案</h2>

      <div className="field">
        <label htmlFor="project-name">專案名稱</label>
        <input
          id="project-name"
          value={name}
          placeholder="例如：秀山分隊興建工程"
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submit()}
        />
        <button type="button" onClick={submit}>
          建立專案
        </button>
      </div>

      {projects.length === 0 ? (
        <p className="hint">還沒有專案。先建立一個專案，再把標單掛上去。</p>
      ) : (
        <ul className="list">
          {projects.map((project) => (
            <li
              key={project.project_id}
              className={`clickable ${project.project_id === selectedId ? "selected" : ""}`}
              onClick={() => onSelect(project.project_id)}
            >
              {project.name}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
