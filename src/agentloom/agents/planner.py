"""Planner agent for bounded, validated workflow generation."""

import json
from collections.abc import Sequence

import structlog
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from agentloom.agents.prompts import build_planner_messages
from agentloom.agents.schemas import WorkflowPlan
from agentloom.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMRequest, ToolDefinition
from agentloom.runtime.validator import validate_workflow

DEFAULT_AGENT_ROLES = ("researcher", "analyst", "writer")
MAX_PLANNER_NODES = 20
MAX_PLANNER_REPAIRS = 2
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class PlannerIssue(BaseModel):
    """One structured reason why a proposed workflow was rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PlannerError(RuntimeError):
    """Base error raised by planning before persistence."""


class PlannerGenerationError(PlannerError):
    """Raised when every bounded workflow repair attempt is invalid."""

    def __init__(self, issues: Sequence[PlannerIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("Planner could not generate a valid workflow")


class PlannerProviderError(PlannerError):
    """Raised when the configured model provider cannot complete planning."""


class Planner:
    """Generate and deterministically validate one workflow plan."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: Sequence[ToolDefinition],
        *,
        model: str,
        agent_roles: Sequence[str] = DEFAULT_AGENT_ROLES,
        max_repairs: int = MAX_PLANNER_REPAIRS,
        timeout_seconds: float = 60,
    ) -> None:
        if not agent_roles:
            raise ValueError("Planner requires at least one agent role")
        if max_repairs < 0:
            raise ValueError("max_repairs must be non-negative")
        self._llm = llm
        self._tools = tuple(tools)
        self._tool_names = frozenset(tool.name for tool in tools)
        self._agent_roles = tuple(agent_roles)
        self._model = model
        self._max_repairs = max_repairs
        self._timeout_seconds = timeout_seconds
        self._logger = structlog.get_logger(__name__)

    @property
    def registered_tools(self) -> frozenset[str]:
        """Return the exact tool names accepted by workflow validation."""

        return self._tool_names

    async def plan(
        self,
        goal: str,
        context: dict[str, JsonValue],
        *,
        max_parallel_nodes: int,
        max_retries: int,
    ) -> WorkflowPlan:
        """Generate a valid plan, feeding deterministic errors into bounded repairs."""

        response_schema = _workflow_plan_schema(self._tool_names)
        messages = build_planner_messages(
            goal,
            context,
            self._agent_roles,
            self._tools,
            max_nodes=MAX_PLANNER_NODES,
            max_parallel_nodes=max_parallel_nodes,
            max_retries=max_retries,
            response_schema=response_schema,
        )
        last_issues: list[PlannerIssue] = []

        for attempt in range(self._max_repairs + 1):
            try:
                response = await self._llm.complete(
                    LLMRequest(
                        model=self._model,
                        messages=messages,
                        response_schema=response_schema,
                        timeout_seconds=self._timeout_seconds,
                    )
                )
            except LLMProviderError as error:
                raise PlannerProviderError("Planner model request failed") from error

            plan, issues = self._validate_output(response.structured_output)
            if plan is not None:
                return plan

            last_issues = issues
            self._logger.warning(
                "planner_output_invalid",
                attempt=attempt + 1,
                issues=[issue.model_dump(mode="json") for issue in issues],
            )
            if attempt == self._max_repairs:
                break
            messages.extend(
                [
                    LLMMessage(
                        role="assistant",
                        content=_visible_output(response.structured_output, response.content),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "Repair the WorkflowPlan and return the complete corrected plan. "
                            f"Validation errors: {_issues_json(issues)}"
                        ),
                    ),
                ]
            )

        raise PlannerGenerationError(last_issues)

    def _validate_output(
        self,
        output: dict[str, JsonValue] | None,
    ) -> tuple[WorkflowPlan | None, list[PlannerIssue]]:
        if output is None:
            return None, [PlannerIssue(path="output", reason="Structured output is required")]
        try:
            plan = WorkflowPlan.model_validate(output)
        except ValidationError as error:
            return None, [
                PlannerIssue(
                    path=".".join(str(part) for part in issue["loc"]),
                    reason=issue["msg"],
                )
                for issue in error.errors(include_url=False)
            ]

        issues = [
            PlannerIssue(path=error.path, reason=error.message)
            for error in validate_workflow(plan, self._tool_names)
        ]
        issues.extend(
            PlannerIssue(
                path=f"nodes.{index}.role",
                reason=f"Agent role '{node.role}' is not available",
            )
            for index, node in enumerate(plan.nodes)
            if node.role not in self._agent_roles
        )
        return (None, issues) if issues else (plan, [])


def _workflow_plan_schema(registered_tools: frozenset[str]) -> dict[str, JsonValue]:
    schema = JSON_OBJECT_ADAPTER.validate_python(WorkflowPlan.model_json_schema())
    schema["examples"] = [_default_workflow_plan(registered_tools).model_dump(mode="json")]
    return schema


def _default_workflow_plan(registered_tools: frozenset[str]) -> WorkflowPlan:
    research_tools = ["web_search"] if "web_search" in registered_tools else []
    nodes: list[dict[str, object]] = []
    for suffix in ("a", "b", "c"):
        nodes.append(
            {
                "key": f"research_{suffix}",
                "name": f"Research subject {suffix.upper()}",
                "role": "researcher",
                "description": f"Research subject {suffix.upper()} for the requested comparison.",
                "system_prompt": "Collect concise facts and preserve source attribution.",
                "depends_on": [],
                "tools": research_tools,
                "output_schema": {
                    "type": "object",
                    "required": ["summary", "sources"],
                    "properties": {
                        "summary": {"type": "string", "minLength": 1},
                        "sources": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "review_criteria": "The summary is factual and includes sources.",
            }
        )
    nodes.append(
        {
            "key": "write_report",
            "name": "Write comparison report",
            "role": "writer",
            "description": "Synthesize the three research results into one report.",
            "system_prompt": "Create a balanced comparison using all upstream results.",
            "depends_on": ["research_a", "research_b", "research_c"],
            "tools": [],
            "output_schema": {
                "type": "object",
                "required": ["report"],
                "properties": {"report": {"type": "string", "minLength": 1}},
            },
            "review_criteria": "The report compares all subjects and preserves attribution.",
        }
    )
    return WorkflowPlan.model_validate({"nodes": nodes, "final_node": "write_report"})


def _visible_output(output: dict[str, JsonValue] | None, content: str | None) -> str:
    if output is not None:
        return json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    return content or "No structured output was returned."


def _issues_json(issues: Sequence[PlannerIssue]) -> str:
    return json.dumps(
        [issue.model_dump(mode="json") for issue in issues],
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "DEFAULT_AGENT_ROLES",
    "MAX_PLANNER_NODES",
    "MAX_PLANNER_REPAIRS",
    "Planner",
    "PlannerError",
    "PlannerGenerationError",
    "PlannerIssue",
    "PlannerProviderError",
]
