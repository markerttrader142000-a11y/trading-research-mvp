"""
Crew 4 — Execution Monitor
---------------------------
Monitors open trades and handles operational exceptions.

This crew is NOT yet wired into the main pipeline (no open trades in MVP).
It is scaffolded here so the architecture is complete and can be activated
when broker execution connectors are added.

Receives: open position data from LangGraph state
Delivers: monitoring actions (hold, partial, tighten_stop, flag_exit, escalate)
"""
from __future__ import annotations

from typing import Any, Dict, List

from crewai import Crew, Task

from agents import exception_handler, trade_monitor
from agents.llm_factory import make_llm


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_execution_monitor(
    open_positions: List[Dict[str, Any]],
    config: dict,
) -> List[Dict[str, Any]]:
    """
    Monitors open positions and suggests actions.
    Returns a list of monitoring action dicts per position.

    Currently returns mock hold actions — will be activated when
    broker connectors deliver live position data.
    """
    if not open_positions:
        return []

    provider = config.get("models", {}).get("analysis", "mock")
    llm = make_llm(provider)

    if llm is None:
        return _mock_monitor(open_positions)

    return _crew_monitor(open_positions, llm)


# ---------------------------------------------------------------------------
# Mock path
# ---------------------------------------------------------------------------

def _mock_monitor(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "asset": pos.get("asset", "UNKNOWN"),
            "action": "hold",
            "reason": "Mock monitor — no live broker data connected yet.",
            "requires_human_review": True,
        }
        for pos in positions
    ]


# ---------------------------------------------------------------------------
# Real LLM path
# ---------------------------------------------------------------------------

def _crew_monitor(positions: List[Dict[str, Any]], llm) -> List[Dict[str, Any]]:
    monitor = trade_monitor(llm)
    handler = exception_handler(llm)
    results = []

    for pos in positions:
        pos_brief = str(pos)

        task_monitor = Task(
            description=(
                f"Review this open position and recommend an action:\n\n{pos_brief}\n\n"
                "Options: hold, tighten_stop, take_partial, flag_exit, escalate_to_human."
            ),
            expected_output=(
                "One of: hold / tighten_stop / take_partial / flag_exit / escalate_to_human, "
                "with a one-sentence justification."
            ),
            agent=monitor,
        )

        task_exception = Task(
            description=(
                f"Check for operational issues in this position:\n\n{pos_brief}\n\n"
                "Look for: fill mismatches, abnormal spread, API lag, position size errors."
            ),
            expected_output=(
                "OK if no issues, or a specific exception description with suggested resolution."
            ),
            agent=handler,
        )

        crew = Crew(
            agents=[monitor, handler],
            tasks=[task_monitor, task_exception],
            verbose=False,
        )

        try:
            result = crew.kickoff()
            results.append({
                "asset": pos.get("asset", "UNKNOWN"),
                "action": "review",
                "reason": str(result)[:200],
                "requires_human_review": True,
            })
        except Exception as exc:
            results.append({
                "asset": pos.get("asset", "UNKNOWN"),
                "action": "escalate_to_human",
                "reason": f"Monitor crew failed: {exc}",
                "requires_human_review": True,
            })

    return results
