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
      <span className="eyebrow">{error ? "执行错误" : "最终输出"}</span>
      <h2>{error ? "运行失败" : "结果"}</h2>
      {typeof report === "string" ? <div className="report-content">{report}</div> : null}
      {typeof report !== "string" ? <pre>{formatJson(error ?? result ?? undefined)}</pre> : null}
    </section>
  );
}
