"""
Crew 5 — Post-Trade Review
---------------------------
Journals closed trades and mines patterns for the LangGraph memory layer.

This crew is scaffolded for the full architecture but not yet wired into the
main pipeline — it activates when trades are executed and closed.

Receives: closed trade data (plan vs execution vs outcome)
Delivers: journal entry (dict) + pattern summary for memory update
"""
from __future__ import annotations

from typing import Any, Dict

from crewai import Crew, Task

from agents import journal_writer, pattern_miner
from agents.llm_factory import make_llm


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_post_trade_review(
    closed_trade: Dict[str, Any],
    config: dict,
) -> Dict[str, Any]:
    """
    Reviews a closed trade and returns a structured journal entry.
    """
    if not closed_trade:
        return {"status": "no_trade_to_review"}

    provider = config.get("models", {}).get("analysis", "mock")
    llm = make_llm(provider)

    if llm is None:
        return _mock_review(closed_trade)

    return _crew_review(closed_trade, llm)


# ---------------------------------------------------------------------------
# Mock path
# ---------------------------------------------------------------------------

def _mock_review(trade: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "asset": trade.get("asset", "UNKNOWN"),
        "outcome": trade.get("outcome", "unknown"),
        "journal": "Mock journal entry — no closed trade data connected yet.",
        "lessons": ["Activate this crew when broker connectors deliver closed trade data."],
        "patterns": [],
        "memory_update": False,
    }


# ---------------------------------------------------------------------------
# Real LLM path
# ---------------------------------------------------------------------------

def _crew_review(trade: Dict[str, Any], llm) -> Dict[str, Any]:
    writer = journal_writer(llm)
    miner = pattern_miner(llm)

    trade_brief = str(trade)

    task_journal = Task(
        description=(
            f"Write a post-trade journal entry for this closed trade:\n\n{trade_brief}\n\n"
            "Include: what the thesis was, what happened, what was done correctly, "
            "what went wrong and what to do differently next time."
        ),
        expected_output=(
            "A clear journal entry with: thesis, execution_notes, what_worked, "
            "what_failed, improvement_suggestion."
        ),
        agent=writer,
    )

    task_pattern = Task(
        description=(
            f"Identify any recurring patterns in this trade result:\n\n{trade_brief}\n\n"
            "Look for: setup type performance, session timing, volatility regime, "
            "broker-specific issues or thesis accuracy."
        ),
        expected_output=(
            "A brief pattern note: pattern_type, asset, session, setup, outcome, "
            "suggested_memory_update (yes/no)."
        ),
        agent=miner,
    )

    crew = Crew(
        agents=[writer, miner],
        tasks=[task_journal, task_pattern],
        verbose=False,
    )

    try:
        result = crew.kickoff()
        return {
            "asset": trade.get("asset", "UNKNOWN"),
            "outcome": trade.get("outcome", "unknown"),
            "journal": str(result)[:500],
            "lessons": ["See journal for full review."],
            "patterns": ["See pattern output for recurring signals."],
            "memory_update": True,
        }
    except Exception as exc:
        return {
            "asset": trade.get("asset", "UNKNOWN"),
            "outcome": "review_failed",
            "journal": f"Post-trade crew failed: {exc}",
            "lessons": [],
            "patterns": [],
            "memory_update": False,
        }
