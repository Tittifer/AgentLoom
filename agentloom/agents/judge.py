"""Bounded judge pipeline shared by queen and worker loops."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JudgeDecision = Literal["accept", "retry", "escalate", "reject"]


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: JudgeDecision
    score: float = Field(ge=0, le=1)
    feedback: str
    issues: list[str] = Field(default_factory=list)


class JudgePipeline:
    """Apply deterministic completion checks before future semantic/human levels."""

    def review(self, content: str, *, iteration: int, max_turns: int) -> JudgeResult:
        if content.strip():
            return JudgeResult(
                decision="accept",
                score=1,
                feedback="输出已通过基础完整性检查。",
            )
        if iteration < max_turns:
            return JudgeResult(
                decision="retry",
                score=0,
                feedback="输出为空，请给出可见结果或调用所需工具。",
                issues=["empty_output"],
            )
        return JudgeResult(
            decision="reject",
            score=0,
            feedback="达到最大轮数后仍未生成有效输出。",
            issues=["empty_output", "turn_budget_exhausted"],
        )


__all__ = ["JudgeDecision", "JudgePipeline", "JudgeResult"]
