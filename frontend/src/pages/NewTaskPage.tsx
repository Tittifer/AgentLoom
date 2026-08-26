import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createTask, planTask, type JsonObject, type TaskCreateInput } from "../api/tasks";
import { formatError } from "../utils/format";

function parseContext(value: string): JsonObject {
  const parsed: unknown = JSON.parse(value);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Context must be a JSON object.");
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
      <Link className="back-link" to="/tasks">← Back to tasks</Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">New workflow</span>
          <h1 id="new-task-title">Create a task</h1>
          <p>Describe the outcome. The Planner will turn it into a validated agent DAG.</p>
        </div>
      </div>

      <form className="panel task-form" onSubmit={handleSubmit}>
        <label>
          <span>Title</span>
          <input maxLength={200} onChange={(event) => setTitle(event.target.value)} required value={title} />
        </label>
        <label>
          <span>Goal</span>
          <textarea onChange={(event) => setGoal(event.target.value)} required rows={6} value={goal} />
        </label>
        <label>
          <span>Context (JSON object)</span>
          <textarea className="code-input" onChange={(event) => setContext(event.target.value)} rows={7} value={context} />
        </label>
        <div className="form-grid">
          <label>
            <span>Maximum parallel nodes</span>
            <input max={20} min={1} onChange={(event) => setMaxParallelNodes(event.target.valueAsNumber)} required type="number" value={maxParallelNodes} />
          </label>
          <label>
            <span>Maximum retries</span>
            <input min={0} onChange={(event) => setMaxRetries(event.target.valueAsNumber)} required type="number" value={maxRetries} />
          </label>
        </div>

        {validationError || createMutation.isError ? (
          <div className="form-error" role="alert">{validationError ?? formatError(createMutation.error)}</div>
        ) : null}

        <div className="form-actions">
          <Link className="secondary-button button-link" to="/tasks">Cancel</Link>
          <button className="primary-button" disabled={createMutation.isPending} type="submit">
            {createMutation.isPending ? "Creating and planning…" : "Create and plan"}
          </button>
        </div>
        {createMutation.isPending ? <p className="planning-note">The Planner is generating and validating the workflow. This may take a moment.</p> : null}
      </form>
    </section>
  );
}
