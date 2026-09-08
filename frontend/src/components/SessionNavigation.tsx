import { useState } from "react";
import { NavLink } from "react-router-dom";

import type { ColonyRead } from "../api/colonies";
import { statusText } from "../utils/format";

interface SessionNavigationProps {
  colonies: ColonyRead[];
  queenId: string;
  creating: boolean;
  onCreate: () => void;
}

export function SessionNavigation({
  colonies,
  queenId,
  creating,
  onCreate,
}: SessionNavigationProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside className={`session-navigation${collapsed ? " is-collapsed" : ""}`}>
      <header className="session-navigation-header">
        <div>
          <span className="section-kicker">工作空间</span>
          <strong>协作会话</strong>
        </div>
        <button
          aria-label={collapsed ? "展开会话导航" : "收起会话导航"}
          className="navigation-toggle"
          onClick={() => setCollapsed((value) => !value)}
          type="button"
        >
          {collapsed ? "›" : "‹"}
        </button>
      </header>

      <div className="navigation-primary">
        <button
          aria-label="新建会话"
          className="new-session-button"
          disabled={creating}
          onClick={onCreate}
          type="button"
        >
          <span aria-hidden="true">▣</span>
          <strong>{creating ? "创建中…" : "新建会话"}</strong>
        </button>
        <NavLink className="navigation-menu-item" to={`/queens/${queenId}`}>
          <span aria-hidden="true">⌘</span><strong>Queen 会话</strong>
        </NavLink>
        <NavLink className="navigation-menu-item" to="/memories">
          <span aria-hidden="true">♧</span><strong>记忆库</strong>
        </NavLink>
        <NavLink className="navigation-menu-item" to="/settings">
          <span aria-hidden="true">⚙</span><strong>用户设置</strong>
        </NavLink>
      </div>

      <div className="navigation-section-heading">
        <span>COLONIES</span><b>{colonies.length}</b>
      </div>

      <nav aria-label="会话导航" className="session-navigation-list">
        {colonies.map((colony) => (
          <NavLink
            className={({ isActive }) => `session-navigation-item${isActive ? " active" : ""}`}
            key={colony.id}
            title={colony.name}
            to={`/colonies/${colony.id}`}
          >
            <span className={`session-status-dot status-dot-${colony.status}`} aria-hidden="true" />
            <span className="session-navigation-copy">
              <strong>{colony.name}</strong>
              <small>{statusText(colony.status)}</small>
            </span>
          </NavLink>
        ))}
      </nav>

      <NavLink className="all-sessions-link" to={`/queens/${queenId}`}>
        <span aria-hidden="true">⚙</span>
        <strong>管理 Queen</strong>
      </NavLink>
      <small className="navigation-version">v0.1.0</small>
    </aside>
  );
}
