import { NavLink, Outlet, useLocation } from "react-router-dom";

function App() {
  const location = useLocation();
  const isWorkspace = /^\/(?:colonies|sessions)\/[^/]+$/.test(location.pathname);

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="brand" to="/queens">
          <span className="brand-mark" aria-hidden="true">✣</span>
          <span><strong>Agent<span>Loom</span></strong><small>多智能体协作空间</small></span>
        </NavLink>
        <nav aria-label="主导航">
          <NavLink className={({ isActive }) => isActive ? "nav-link active" : "nav-link"} to="/queens">
            <span aria-hidden="true">◇</span> Queen
          </NavLink>
          <NavLink className={({ isActive }) => isActive ? "nav-link active" : "nav-link"} to="/memories">
            <span aria-hidden="true">♧</span> 记忆
          </NavLink>
          <NavLink className={({ isActive }) => isActive ? "nav-link active" : "nav-link"} to="/settings">
            <span aria-hidden="true">⚙</span> 设置
          </NavLink>
          <span className="profile-avatar" aria-label="本地用户">U</span>
        </nav>
      </header>
      <main className={`page-container${isWorkspace ? " workspace-container" : ""}`}>
        <Outlet />
      </main>
    </div>
  );
}

export default App;
