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

      <button
        aria-label="新建会话"
        className="new-session-button"
        disabled={creating}
        onClick={onCreate}
        type="button"
      >
        <span aria-hidden="true">＋</span>
        <strong>{creating ? "创建中…" : "新建会话"}</strong>
      </button>

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
        <span aria-hidden="true">⌂</span>
        <strong>管理全部会话</strong>
      </NavLink>
    </aside>
  );
}
