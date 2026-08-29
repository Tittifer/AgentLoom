import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listColonies } from "../api/colonies";
import { formatDateTime, formatError, statusText } from "../utils/format";

export function ColonyListPage() {
  const query = useQuery({ queryKey: ["colonies"], queryFn: listColonies });

  return (
    <section aria-labelledby="colonies-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">HIVE COLONY</span>
          <h1 id="colonies-title">协作空间</h1>
          <p>每个 Colony 都有一个持续对话的 Queen，并按任务动态派生并行 Worker。</p>
        </div>
        <Link className="primary-button button-link" to="/colonies/new">创建 Colony</Link>
      </div>

      {query.isLoading ? <div className="panel loading-panel">正在加载 Colony…</div> : null}
      {query.isError ? (
        <div className="panel error-panel">
          <h2>无法加载 Colony</h2>
          <p>{formatError(query.error)}</p>
        </div>
      ) : null}
      {query.data?.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">蜂</div>
          <h2>创建第一个 Colony</h2>
          <p>从一个目标开始，与 Queen 协作完成研究、分析或执行工作。</p>
          <Link className="primary-button button-link" to="/colonies/new">立即创建</Link>
        </div>
      ) : null}
      <div className="colony-card-grid">
        {query.data?.map((colony) => (
          <Link className="colony-card" key={colony.id} to={`/colonies/${colony.id}`}>
            <header>
              <span className="colony-avatar">Q</span>
              <span className={`status-pill status-${colony.status}`}>{statusText(colony.status)}</span>
            </header>
            <h2>{colony.name}</h2>
            <p>{colony.description || "暂无描述"}</p>
            <footer>
              <span>{colony.queen_profile}</span>
              <time>{formatDateTime(colony.updated_at)}</time>
            </footer>
          </Link>
        ))}
      </div>
    </section>
  );
}
