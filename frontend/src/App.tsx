import { NavLink, Outlet } from "react-router-dom";

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="brand" to="/tasks">
          <span className="brand-mark" aria-hidden="true">
            AL
          </span>
          <span>
            <strong>AgentLoom</strong>
            <small>多智能体协作工作台</small>
          </span>
        </NavLink>
        <nav aria-label="主导航">
          <NavLink className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")} to="/tasks">
            任务
          </NavLink>
        </nav>
      </header>
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}

export default App;

