"""Tests for the bounded deterministic Judge pipeline."""

from agentloom.agents.judge import JudgePipeline


def test_judge_accepts_visible_content() -> None:
    result = JudgePipeline().review("完成", iteration=1, max_turns=2)
    assert result.decision == "accept"
    assert result.score == 1


def test_judge_retries_then_rejects_empty_content() -> None:
    judge = JudgePipeline()
    retry = judge.review(" ", iteration=1, max_turns=2)
    rejected = judge.review("", iteration=2, max_turns=2)
    assert retry.decision == "retry"
    assert rejected.decision == "reject"
    assert "turn_budget_exhausted" in rejected.issues
