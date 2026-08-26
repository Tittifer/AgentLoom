import type { JsonObject } from "../api/tasks";
import { formatJson } from "../utils/format";

interface ResultViewerProps {
  result: JsonObject | null;
  error: JsonObject | null;
}

export function ResultViewer({ result, error }: ResultViewerProps) {
  if (!result && !error) {
    return null;
  }

  const report = result?.report;
  return (
    <section className={`panel result-viewer ${error ? "error-panel" : ""}`}>
      <span className="eyebrow">{error ? "Execution error" : "Final output"}</span>
      <h2>{error ? "Run failed" : "Result"}</h2>
      {typeof report === "string" ? <div className="report-content">{report}</div> : null}
      {typeof report !== "string" ? <pre>{formatJson(error ?? result ?? undefined)}</pre> : null}
    </section>
  );
}
