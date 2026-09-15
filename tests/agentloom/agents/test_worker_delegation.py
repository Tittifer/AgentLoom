"""Tests for Hive-style Colony delegation rules."""

from agentloom.agents.worker_delegation import COLONY_DELEGATION_PROMPT


def test_delegation_prompt_defines_rows_as_dispatch_units_and_queen_pilot() -> None:
    assert "一行必须对应一个可以独立派发" in COLONY_DELEGATION_PROMPT
    assert "不得把一个指标、引用或报告单元格" in COLONY_DELEGATION_PROMPT
    assert "你亲自完成第一行 Pilot" in COLONY_DELEGATION_PROMPT
    assert "run_playbook" in COLONY_DELEGATION_PROMPT
