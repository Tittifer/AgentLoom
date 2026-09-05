import { NavLink, Outlet, useLocation } from "react-router-dom";

function App() {
  const location = useLocation();
  const isWorkspace = /^\/colonies\/[^/]+$/.test(location.pathname);

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="brand" to="/queens">
          <span className="brand-mark" aria-hidden="true">AL</span>
          <span><strong>AgentLoom</strong><small>多智能体协作助手</small></span>
        </NavLink>
        <nav aria-label="主导航">
          <NavLink className={({ isActive }) => isActive ? "nav-link active" : "nav-link"} to="/queens">
            Queen
          </NavLink>
        </nav>
      </header>
      <main className={`page-container${isWorkspace ? " workspace-container" : ""}`}>
        <Outlet />
      </main>
    </div>
  );
}

export default App;
