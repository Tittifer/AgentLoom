import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createTask, planTask, type JsonObject, type TaskCreateInput } from "../api/tasks";
import { formatError } from "../utils/format";

function parseContext(value: string): JsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("上下文必须是有效的 JSON 对象。");
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("上下文必须是 JSON 对象。");
  }
  return parsed as JsonObject;
}

export function NewTaskPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [context, setContext] = useState("{}");
  const [maxParallelNodes, setMaxParallelNodes] = useState(3);
  const [maxRetries, setMaxRetries] = useState(2);
  const [validationError, setValidationError] = useState<string>();

  const createMutation = useMutation({
    mutationFn: async (input: TaskCreateInput) => {
      const task = await createTask(input);
      await planTask(task.id);
      return task;
    },
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      navigate(`/tasks/${task.id}`);
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(undefined);
    try {
      createMutation.mutate({
        title,
        goal,
        context: parseContext(context),
        max_parallel_nodes: maxParallelNodes,
        max_retries: maxRetries,
      });
    } catch (error) {
      setValidationError(formatError(error));
    }
  }

  return (
    <section className="narrow-page" aria-labelledby="new-task-title">
      <Link className="back-link" to="/tasks">← 返回任务列表</Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">新工作流</span>
          <h1 id="new-task-title">创建任务</h1>
          <p>描述期望结果，规划器会将其转换为经过校验的智能体 DAG。</p>
        </div>
      </div>

      <form className="panel task-form" onSubmit={handleSubmit}>
        <label>
          <span>标题</span>
          <input maxLength={200} onChange={(event) => setTitle(event.target.value)} required value={title} />
        </label>
        <label>
          <span>目标</span>
          <textarea onChange={(event) => setGoal(event.target.value)} required rows={6} value={goal} />
        </label>
        <label>
          <span>上下文（JSON 对象）</span>
          <textarea className="code-input" onChange={(event) => setContext(event.target.value)} rows={7} value={context} />
        </label>
        <div className="form-grid">
          <label>
            <span>最大并行节点数</span>
            <input max={20} min={1} onChange={(event) => setMaxParallelNodes(event.target.valueAsNumber)} required type="number" value={maxParallelNodes} />
          </label>
          <label>
            <span>最大重试次数</span>
            <input min={0} onChange={(event) => setMaxRetries(event.target.valueAsNumber)} required type="number" value={maxRetries} />
          </label>
        </div>

        {validationError || createMutation.isError ? (
          <div className="form-error" role="alert">{validationError ?? formatError(createMutation.error)}</div>
        ) : null}

        <div className="form-actions">
          <Link className="secondary-button button-link" to="/tasks">取消</Link>
          <button className="primary-button" disabled={createMutation.isPending} type="submit">
            {createMutation.isPending ? "正在创建并规划…" : "创建并规划"}
          </button>
        </div>
        {createMutation.isPending ? <p className="planning-note">规划器正在生成并校验工作流，请稍候。</p> : null}
      </form>
    </section>
  );
}
