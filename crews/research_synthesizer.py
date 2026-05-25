"""
Crew 1 — Research Synthesizer
------------------------------
Replaces the mock in research.py with a structured CrewAI workflow.

Receives: List[MarketCandidate] from the scanner (via LangGraph state)
Delivers: List[ResearchItem] with real or mock-structured research per asset

With mock LLM (default): returns the same structured placeholders as before,
but now via proper CrewAI Task + Agent pipeline, ready to receive real LLMs.

With real LLM (Perplexity / Claude / GPT): each agent calls the model API
and returns grounded research with real sources and catalysts.
"""
from __future__ import annotations

import json
from typing import List

from crewai import Crew, Process, Task

from agents import (
    contrarian_checker,
    macro_research_analyst,
    market_context_analyst,
)
from agents.llm_factory import make_llm
from schemas import MarketCandidate, ResearchItem


# ---------------------------------------------------------------------------
# Public entry point called by LangGraph node
# ---------------------------------------------------------------------------

def run_research_synthesizer(
    candidates: List[MarketCandidate],
    config: dict,
) -> List[ResearchItem]:
    """
    Runs the Research Synthesizer Crew for each candidate.
    Returns a list of ResearchItem objects.
    """
    provider = config.get("models", {}).get("research", "mock")
    llm = make_llm(provider)

    # With mock LLM, skip actual crew execution and return structured placeholders.
    # This keeps the pipeline working without API keys.
    if llm is None:
        return _mock_research(candidates)

    return _crew_research(candidates, llm)


# ---------------------------------------------------------------------------
# Mock path (no API keys needed)
# ---------------------------------------------------------------------------

def _mock_research(candidates: List[MarketCandidate]) -> List[ResearchItem]:
    """
    Structured mock research — same logic as original research.py but now
    living inside the CrewAI layer, ready to be replaced by real LLM calls.
    """
    items: List[ResearchItem] = []
    for candidate in candidates:
        if candidate.market == "ctrader":
            items.append(_ctrader_mock(candidate))
        elif candidate.market == "stocks":
            items.append(_stocks_mock(candidate))
        else:
            items.append(_generic_mock(candidate))
    return items


def _ctrader_mock(candidate: MarketCandidate) -> ResearchItem:
    metrics = candidate.metrics or {}
    scan_score = float(metrics.get("scan_score", 0))
    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=(
            f"{candidate.asset} selected from cTrader trendbar data. "
            "Price-action-only research — no external news context yet."
        ),
        bullish_factors=[
            "Recent trendbar movement may indicate short-term momentum.",
            "Candidate passed configured movement/range thresholds.",
        ],
        bearish_factors=[
            "Price-action-only signals can be false breakouts.",
            "No macro/news filter connected yet.",
        ],
        catalysts=[candidate.reason],
        macro_events=[],
        news_risks=["External news and calendar risk not connected in this version."],
        sources=[candidate.source_hint or "cTrader Open API trendbars"],
        source_quality_score=min(0.95, 0.65 + scan_score / 10),
    )


def _stocks_mock(candidate: MarketCandidate) -> ResearchItem:
    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=(
            f"{candidate.asset} selected by Alpaca scanner based on recent price movement. "
            "Market-data-driven only — no news or fundamental context yet."
        ),
        bullish_factors=[
            "Recent price momentum may indicate institutional attention or continuation.",
            "Candidate passed the configured movement threshold.",
        ],
        bearish_factors=[
            "Price movement alone is not a complete catalyst.",
            "Requires chart validation and news check.",
        ],
        catalysts=[candidate.reason],
        macro_events=[],
        news_risks=["News context not connected in this version."],
        sources=[candidate.source_hint or "Alpaca historical stock bars"],
        source_quality_score=0.72,
    )


def _generic_mock(candidate: MarketCandidate) -> ResearchItem:
    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=(
            f"{candidate.asset} is a mock research item. "
            "Replace with real Perplexity/LLM research when API keys are available."
        ),
        bullish_factors=["Mock bullish factor — replace with real research."],
        bearish_factors=["Mock bearish factor — replace with real research."],
        catalysts=[candidate.reason],
        macro_events=[],
        news_risks=["MOCK: no real news connected."],
        sources=["MOCK_SOURCE: replace with Perplexity citations"],
        source_quality_score=0.60,
    )


# ---------------------------------------------------------------------------
# Real LLM path (activated when API keys are set)
# ---------------------------------------------------------------------------

def _crew_research(candidates: List[MarketCandidate], llm) -> List[ResearchItem]:
    """
    Runs the full 3-agent crew for each candidate.
    Agents: Macro Research Analyst + Market Context Analyst + Contrarian Checker
    """
    analyst = macro_research_analyst(llm)
    context = market_context_analyst(llm)
    contrarian = contrarian_checker(llm)

    items: List[ResearchItem] = []

    for candidate in candidates:
        candidate_brief = (
            f"Asset: {candidate.asset}\n"
            f"Market: {candidate.market}\n"
            f"Reason selected: {candidate.reason}\n"
            f"Catalyst type: {candidate.catalyst_type}\n"
            f"Timeframe: {candidate.timeframe}\n"
            f"Source hint: {candidate.source_hint}\n"
            f"Metrics: {json.dumps(candidate.metrics)}"
        )

        task_macro = Task(
            description=(
                f"Research the following asset and provide macro context, "
                f"key catalysts, upcoming events and sentiment summary.\n\n{candidate_brief}\n\n"
                "IMPORTANT: Respond ONLY with a valid JSON object. No prose outside the JSON. "
                "Required keys: macro_summary (string), bullish_factors (list of strings), "
                "bearish_factors (list of strings), catalysts (list of strings), "
                "macro_events (list of strings), news_risks (list of strings), "
                "sources (list of strings), source_quality_score (float 0.0-1.0)."
            ),
            expected_output=(
                'A JSON object, e.g.: {"macro_summary": "...", "bullish_factors": [...], '
                '"bearish_factors": [...], "catalysts": [...], "macro_events": [...], '
                '"news_risks": [...], "sources": [...], "source_quality_score": 0.75}'
            ),
            agent=analyst,
        )

        task_context = Task(
            description=(
                f"Analyse the market structure, session context and volatility regime "
                f"for the following candidate:\n\n{candidate_brief}\n\n"
                f"Use the macro research from the previous task as context."
            ),
            expected_output=(
                "A brief market context note covering: session timing, volatility, "
                "technical structure and any execution-relevant observations."
            ),
            agent=context,
        )

        task_contrarian = Task(
            description=(
                f"Challenge the research for this candidate and identify the top risks "
                f"and reasons NOT to trade it:\n\n{candidate_brief}"
            ),
            expected_output=(
                "A list of 2-4 specific reasons why this trade could fail, "
                "including hidden risks, false-signal scenarios and timing concerns."
            ),
            agent=contrarian,
        )

        crew = Crew(
            agents=[analyst, context, contrarian],
            tasks=[task_macro, task_context, task_contrarian],
            process=Process.sequential,
            verbose=True,
        )

        try:
            crew.kickoff()
            # Use task_macro output (JSON) as primary — it has the structured fields.
            # task_context and task_contrarian outputs are text; we fold them in as
            # additional news_risks if available.
            macro_raw = str(task_macro.output.raw if task_macro.output else "")
            contrarian_raw = str(task_contrarian.output.raw if task_contrarian.output else "")
            items.append(_parse_crew_output(candidate, macro_raw, contrarian_raw))
        except Exception as exc:
            # Graceful fallback to mock if crew fails
            item = _generic_mock(candidate)
            item.news_risks.append(f"Crew execution failed: {exc}")
            items.append(item)

    return items


def _parse_crew_output(candidate: MarketCandidate, crew_output, contrarian_raw: str = "") -> ResearchItem:
    """
    Parses the Macro task JSON output into a ResearchItem.
    Folds contrarian risks into news_risks if available.

    Strategy (in order):
    1. Try to find and parse a JSON block in the macro output.
    2. Fall back to keyword-based line extraction.
    3. Use raw text as summary with safe defaults.
    """
    raw = str(crew_output)

    # ── 1. Try JSON extraction ──────────────────────────────────────────────
    data = _extract_json(raw)
    if data:
        news_risks = _to_list(data.get("news_risks", []))
        # Append first 2 contrarian points as additional risk notes
        if contrarian_raw:
            for line in contrarian_raw.splitlines():
                line = line.strip().lstrip("*#-1234567890. ")
                if len(line) > 30 and not any(line in r for r in news_risks):
                    news_risks.append(line)
                    if len(news_risks) >= 5:
                        break
        return ResearchItem(
            asset=candidate.asset,
            market=candidate.market,
            summary=str(data.get("macro_summary", data.get("summary", raw[:400]))),
            bullish_factors=_to_list(data.get("bullish_factors", [])),
            bearish_factors=_to_list(data.get("bearish_factors", [])),
            catalysts=_to_list(data.get("catalysts", [candidate.reason])),
            macro_events=_to_list(data.get("macro_events", [])),
            news_risks=news_risks,
            sources=_to_list(data.get("sources", ["LLM research output"])),
            source_quality_score=float(data.get("source_quality_score", 0.75)),
        )

    # ── 2. Keyword extraction fallback ─────────────────────────────────────
    bullish = _extract_lines(raw, ("bullish", "positive", "upside", "catalyst"))
    bearish = _extract_lines(raw, ("bearish", "negative", "downside", "risk", "concern"))

    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=raw[:400],
        bullish_factors=bullish or [f"LLM flagged {candidate.asset} as a candidate."],
        bearish_factors=bearish or ["Review full crew output for risks."],
        catalysts=[candidate.reason],
        macro_events=[],
        news_risks=[],
        sources=["LLM research output"],
        source_quality_score=0.72,
    )


# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """
    Finds the first valid JSON object in text.
    Handles ```json ... ``` fences and bare braces.
    """
    import re
    # Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # Find first bare {...}
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _to_list(value) -> list:
    """Ensures the value is a flat list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value] or []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


def _extract_lines(text: str, keywords: tuple) -> list:
    """
    Returns up to 3 lines that contain any of the given keywords.
    Used as fallback when JSON parsing fails.
    """
    results = []
    for line in text.splitlines():
        lower = line.lower()
        if any(k in lower for k in keywords) and len(line.strip()) > 15:
            results.append(line.strip().lstrip("•-*").strip())
            if len(results) >= 3:
                break
    return results
