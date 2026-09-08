import { SessionNavigation } from "../components/SessionNavigation";

export function WorkspaceEntryPage() {
  return (
    <section className="workspace-page" aria-labelledby="workspace-entry-title">
      <div className="workspace-shell entry-workspace-shell">
        <SessionNavigation />
        <div className="conversation-workspace workspace-entry">
          <div className="chat-empty">
            <div className="empty-icon" aria-hidden="true">Q</div>
            <h1 id="workspace-entry-title">选择一个 Queen</h1>
            <p>从左侧选择 Queen，即可打开最近会话；也可以直接新建 Queen。</p>
          </div>
        </div>
      </div>
    </section>
  );
}
