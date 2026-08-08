function App() {
  return (
    <main className="app-shell">
      <section className="hero" aria-labelledby="page-title">
        <span className="eyebrow">Multi-agent collaboration</span>
        <h1 id="page-title">AgentLoom</h1>
        <p>
          The frontend workspace is ready. Task planning, DAG execution, and live run views
          will be added in the next implementation steps.
        </p>
        <a className="health-link" href="http://localhost:8000/health">
          Check backend health
        </a>
      </section>
    </main>
  );
}

export default App;

