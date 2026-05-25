"""
Crew 3 — Trade Plan
--------------------
Replaces the mock in opportunity.py with a structured CrewAI workflow.

Receives: ResearchItem + validation result from Crew 2
Delivers: TradeOpportunity with a full plan (entry, SL, TP, thesis, etc.)

With mock LLM: returns the same structured opportunity as opportunity.py but
               now via proper agent/task pipeline, ready for real LLMs.

With real LLM (Claude / GPT): the Trade Planner agent generates a plan from
               the research and validation context, returned as structured JSON.
"""
from __future__ import annotations

import json
from typing import Optional

from crewai import Crew, Task

from agents import (
    execution_instruction_formatter,
    position_sizing_assistant,
    trade_planner,
)
from agents.llm_factory import make_llm
from schemas import ResearchItem, TradeOpportunity


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_trade_plan(
    research: ResearchItem,
    validation: dict,
    config: dict,
) -> Optional[TradeOpportunity]:
    """
    Builds a trade plan from validated research.
    Returns None if planning fails or the setup is not valid.
    """
    if not validation.get("validated", False):
        return None

    provider = config.get("models", {}).get("analysis", "mock")
    llm = make_llm(provider)

    if llm is None:
        return _mock_plan(research, validation, config)

    return _crew_plan(research, validation, llm)


# ---------------------------------------------------------------------------
# Mock path
# ---------------------------------------------------------------------------

def _mock_plan(
    research: ResearchItem,
    validation: dict,
    config: dict,
) -> Optional[TradeOpportunity]:
    """
    Structured mock plan — same logic as opportunity.py but now inside the
    CrewAI layer. Returns a TradeOpportunity for every validated candidate.
    """
    asset = research.asset
    market = research.market
    catalyst = research.catalysts[0] if research.catalysts else "No catalyst"
    timeframe = config.get("timeframe", "intraday_or_swing")

    # Determine direction from catalyst text
    direction = "long"
    if "downside" in catalyst.lower() or "short" in catalyst.lower():
        direction = "short"

    # Use confidence from validation or default
    confidence = float(validation.get("probability_score", 0.60))

    # Extract metrics if present (cTrader candidates)
    metrics: dict = {}
    if market == "ctrader":
        metrics = _parse_ctrader_metrics(catalyst)
        move_pct = abs(metrics.get("move_pct", 0.0))
        range_pct = metrics.get("range_pct", 0.0)
        confidence = min(0.78, 0.52 + move_pct * 0.08 + range_pct * 0.04)

    return TradeOpportunity(
        asset=asset,
        market=market,
        direction=direction,
        setup_type=f"{market}_price_action_watchlist" if market == "ctrader" else "watchlist",
        thesis=(
            f"{asset} is a watchlist candidate. {research.summary[:200]}"
        ),
        counter_thesis=(
            research.bearish_factors[0]
            if research.bearish_factors
            else "Move may be exhausted or unsupported by broader context."
        ),
        catalyst=catalyst,
        timeframe=timeframe,
        confidence_initial=round(confidence, 3),
        entry_logic="Wait for chart confirmation in the scan direction before considering entry.",
        stop_logic="Invalidate if price reverses through recent structure or spread widens.",
        target_logic="Only consider if nearby structure allows at least 1.5R.",
        invalidation_conditions=[
            "No clean continuation or pullback structure.",
            "Spread widens materially.",
            "Upcoming macro/news event conflicts with direction.",
        ],
        requires_chart_validation=True,
        requires_human_approval=True,
        metrics=metrics,
    )


def _parse_ctrader_metrics(catalyst: str) -> dict:
    import re

    def find(pattern: str) -> float:
        match = re.search(pattern, catalyst)
        return float(match.group(1)) if match else 0.0

    period_match = re.search(r"period=([A-Z0-9]+)", catalyst)
    return {
        "move_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback move"),
        "last_bar_move_pct": find(r"([-+]?\d+(?:\.\d+)?)% last-bar move"),
        "range_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback range"),
        "period": period_match.group(1) if period_match else None,
    }


# ---------------------------------------------------------------------------
# Real LLM path
# ---------------------------------------------------------------------------

def _crew_plan(
    research: ResearchItem,
    validation: dict,
    llm,
) -> Optional[TradeOpportunity]:
    planner = trade_planner(llm)
    sizer = position_sizing_assistant(llm)
    formatter = execution_instruction_formatter(llm)

    research_brief = (
        f"Asset: {research.asset}\n"
        f"Market: {research.market}\n"
        f"Summary: {research.summary}\n"
        f"Bullish factors: {research.bullish_factors}\n"
        f"Bearish factors: {research.bearish_factors}\n"
        f"Catalysts: {research.catalysts}\n"
        f"News risks: {research.news_risks}\n"
        f"Validation probability: {validation.get('probability_score')}\n"
        f"Risk notes: {validation.get('risk_notes')}"
    )

    task_plan = Task(
        description=(
            f"Build a complete trade plan for this validated setup:\n\n{research_brief}\n\n"
            "IMPORTANT: Respond ONLY with a valid JSON object. No prose outside the JSON. "
            "Required keys: direction (long/short/neutral), setup_type (string), "
            "thesis (string), counter_thesis (string), entry_logic (string), "
            "stop_logic (string), target_logic (string), "
            "invalidation_conditions (list of strings), confidence_initial (float 0.0-1.0). "
            "Minimum R:R must be 1.5. No vague entries allowed."
        ),
        expected_output=(
            'A JSON object, e.g.: {"direction": "long", "setup_type": "breakout", '
            '"thesis": "...", "counter_thesis": "...", "entry_logic": "...", '
            '"stop_logic": "...", "target_logic": "...", '
            '"invalidation_conditions": [...], "confidence_initial": 0.65}'
        ),
        agent=planner,
    )

    task_size = Task(
        description=(
            f"Suggest a theoretical position size for this plan based on the research:\n\n"
            f"{research_brief}"
        ),
        expected_output=(
            "A sizing recommendation: small/medium/large relative to account risk, "
            "with a one-sentence justification. NOT a final size — advisory only."
        ),
        agent=sizer,
    )

    task_format = Task(
        description=(
            f"Format the trade plan as a clean execution payload for the broker connector. "
            f"Asset: {research.asset}, Market: {research.market}."
        ),
        expected_output=(
            "A structured payload summary: order_type, direction, entry_zone, stop_zone, "
            "target_zone, ttl_hours, tags."
        ),
        agent=formatter,
    )

    crew = Crew(
        agents=[planner, sizer, formatter],
        tasks=[task_plan, task_size, task_format],
        verbose=False,
    )

    try:
        result = crew.kickoff()
        # Parse raw output — structured JSON parsing activated when LLMs return clean JSON
        return _parse_plan_output(research, validation, str(result))
    except Exception as exc:
        # Fallback to mock on crew error
        plan = _mock_plan(research, validation, {})
        if plan:
            plan.invalidation_conditions.append(f"Crew plan failed, using mock: {exc}")
        return plan


def _parse_plan_output(
    research: ResearchItem,
    validation: dict,
    raw: str,
) -> TradeOpportunity:
    """
    Parses crew output into a TradeOpportunity.

    Strategy (in order):
    1. Try to find and parse a JSON block (the planner is prompted to emit JSON).
    2. Fall back to keyword line extraction for individual fields.
    3. Use safe defaults derived from research and validation context.
    """
    # ── 1. Try JSON extraction ──────────────────────────────────────────────
    data = _extract_json(raw)

    # Helper: pull a field from JSON or fall back to default
    def jget(key: str, default):
        return data.get(key, default) if data else default

    direction = str(jget("direction", _infer_direction(research))).lower()
    if direction not in ("long", "short", "neutral"):
        direction = _infer_direction(research)

    thesis = str(jget("thesis", raw[:300]))
    counter_thesis = str(jget("counter_thesis",
        research.bearish_factors[0] if research.bearish_factors
        else "No counter-thesis extracted."))
    entry_logic = str(jget("entry_logic", "Wait for chart confirmation before entry."))
    stop_logic = str(jget("stop_logic", "Invalidate if price reverses through key structure."))
    target_logic = str(jget("target_logic", "Target only if nearby structure allows ≥ 1.5R."))
    setup_type = str(jget("setup_type", "llm_generated_plan"))
    confidence = float(jget("confidence_initial",
        validation.get("probability_score", 0.65)))
    invalidation = _to_list(jget("invalidation_conditions", []))
    if not invalidation:
        invalidation = research.news_risks or ["Review crew output for invalidation conditions."]

    # ── 2. Keyword extraction if JSON was empty ─────────────────────────────
    if not data:
        entry_line = _extract_first_line(raw, ("entry", "buy", "long", "short", "sell"))
        stop_line = _extract_first_line(raw, ("stop", "sl", "invalidat", "reverse"))
        target_line = _extract_first_line(raw, ("target", "tp", "profit", "exit"))
        if entry_line:
            entry_logic = entry_line
        if stop_line:
            stop_logic = stop_line
        if target_line:
            target_logic = target_line

    return TradeOpportunity(
        asset=research.asset,
        market=research.market,
        direction=direction,
        setup_type=setup_type,
        thesis=thesis,
        counter_thesis=counter_thesis,
        catalyst=research.catalysts[0] if research.catalysts else "LLM-generated catalyst.",
        timeframe="intraday_or_swing",
        confidence_initial=round(min(1.0, max(0.0, confidence)), 3),
        entry_logic=entry_logic,
        stop_logic=stop_logic,
        target_logic=target_logic,
        invalidation_conditions=invalidation,
        requires_chart_validation=True,
        requires_human_approval=True,
    )


# ---------------------------------------------------------------------------
# Parsing helpers (shared with research_synthesizer pattern)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Finds the first valid JSON object in text."""
    import re
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _to_list(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


def _infer_direction(research: ResearchItem) -> str:
    catalyst = research.catalysts[0].lower() if research.catalysts else ""
    if any(w in catalyst for w in ("downside", "short", "bearish", "sell")):
        return "short"
    return "long"


def _extract_first_line(text: str, keywords: tuple) -> str:
    for line in text.splitlines():
        lower = line.lower()
        if any(k in lower for k in keywords) and len(line.strip()) > 15:
            return line.strip().lstrip("•-*").strip()
    return ""
