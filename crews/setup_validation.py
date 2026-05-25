"""
Crew 2 — Setup Validation
--------------------------
Validates trade candidates against strategy criteria before a plan is built.

Receives: TradeOpportunity candidate + ResearchItem context
Delivers: dict with validation_result, risk_notes, probability_score

With mock LLM: auto-approves candidates with direction != neutral and
               confidence >= threshold. Same logic as risk_filter.py but
               now as a crew workflow, ready for real LLM validation.

With real LLM: agents debate the setup, check the checklist and annotate risks.
"""
from __future__ import annotations

import json
from typing import List

from crewai import Crew, Task

from agents import probability_scorer, risk_annotation_agent, setup_validator
from agents.llm_factory import make_llm
from schemas import ResearchItem, TradeOpportunity


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_setup_validation(
    opportunity: TradeOpportunity,
    research: ResearchItem,
    config: dict,
) -> dict:
    """
    Validates a single trade opportunity.
    Returns a dict with: validated (bool), probability_score (float),
    risk_notes (list[str]), rejection_reason (str or None).
    """
    provider = config.get("models", {}).get("analysis", "mock")
    llm = make_llm(provider)

    if llm is None:
        return _mock_validation(opportunity, research, config)

    return _crew_validation(opportunity, research, llm)


# ---------------------------------------------------------------------------
# Mock path
# ---------------------------------------------------------------------------

def _mock_validation(
    opportunity: TradeOpportunity,
    research: ResearchItem,
    config: dict,
) -> dict:
    min_confidence = float(config.get("risk", {}).get("min_confidence", 0.55))
    checks: List[str] = []

    if opportunity.direction == "neutral":
        checks.append("No clear directional bias.")
    if not opportunity.catalyst:
        checks.append("No clear catalyst defined.")
    if not opportunity.invalidation_conditions:
        checks.append("No invalidation conditions specified.")
    if opportunity.confidence_initial < min_confidence:
        checks.append(
            f"Confidence below minimum "
            f"({opportunity.confidence_initial:.2f} < {min_confidence:.2f})."
        )

    validated = len(checks) == 0
    return {
        "validated": validated,
        "probability_score": opportunity.confidence_initial if validated else 0.0,
        "risk_notes": checks if checks else [
            "Execution disabled — human approval required.",
            "Chart validation required before any real trade.",
        ],
        "rejection_reason": "; ".join(checks) if checks else None,
    }


# ---------------------------------------------------------------------------
# Real LLM path
# ---------------------------------------------------------------------------

def _crew_validation(
    opportunity: TradeOpportunity,
    research: ResearchItem,
    llm,
) -> dict:
    validator = setup_validator(llm)
    scorer = probability_scorer(llm)
    annotator = risk_annotation_agent(llm)

    setup_brief = (
        f"Asset: {opportunity.asset}\n"
        f"Direction: {opportunity.direction}\n"
        f"Setup type: {opportunity.setup_type}\n"
        f"Thesis: {opportunity.thesis}\n"
        f"Counter-thesis: {opportunity.counter_thesis}\n"
        f"Catalyst: {opportunity.catalyst}\n"
        f"Entry logic: {opportunity.entry_logic}\n"
        f"Stop logic: {opportunity.stop_logic}\n"
        f"Target logic: {opportunity.target_logic}\n"
        f"Invalidation: {opportunity.invalidation_conditions}\n"
        f"Confidence initial: {opportunity.confidence_initial}\n"
        f"Research summary: {research.summary}"
    )

    task_validate = Task(
        description=(
            f"Validate this trade setup against the strategy checklist:\n\n{setup_brief}\n\n"
            "Checklist: trigger defined, context aligned, invalidation clear, "
            "R:R >= 1.5, no conflicting news, timing acceptable."
        ),
        expected_output=(
            "VALIDATED or REJECTED with specific reasons. "
            "If rejected, list exact checklist items that failed."
        ),
        agent=validator,
    )

    task_score = Task(
        description=(
            f"Score the probability of success for this setup:\n\n{setup_brief}"
        ),
        expected_output=(
            "A probability score between 0.0 and 1.0 with a one-sentence justification."
        ),
        agent=scorer,
    )

    task_annotate = Task(
        description=(
            f"Write specific risk notes for this setup:\n\n{setup_brief}"
        ),
        expected_output=(
            "A list of 2-4 specific, actionable risk notes the trader must be aware of."
        ),
        agent=annotator,
    )

    crew = Crew(
        agents=[validator, scorer, annotator],
        tasks=[task_validate, task_score, task_annotate],
        verbose=False,
    )

    try:
        result = crew.kickoff()
        raw = str(result)
        validated = "VALIDATED" in raw.upper() and "REJECTED" not in raw.upper()
        return {
            "validated": validated,
            "probability_score": opportunity.confidence_initial,
            "risk_notes": [raw[:300]],
            "rejection_reason": None if validated else raw[:200],
        }
    except Exception as exc:
        return {
            "validated": False,
            "probability_score": 0.0,
            "risk_notes": [f"Crew validation failed: {exc}"],
            "rejection_reason": f"Crew error: {exc}",
        }
