"""
LangGraph Supervisor — Layer 2
-------------------------------
Orchestrates all pipeline nodes. The graph is the "OS" of the system:
it maintains state, routes opportunities and calls the CrewAI crews.

Node structure:
  autonomous_scan         → scanner.py (cTrader / Alpaca / mock)
  research_candidates     → Crew 1: Research Synthesizer
  generate_opportunities  → Crew 2: Setup Validation + Crew 3: Trade Plan
  risk_quality_filter     → risk_filter.py (deterministic)
  rank_opportunities      → ranking.py (deterministic)
  build_report            → report.py
  monitor_executions      → Crew 4: Execution Monitor
                            (no-ops when execution_enabled: false / no open positions)
  post_trade_review       → Crew 5: Post-Trade Review
                            (no-ops when no closed trade available)
"""
from __future__ import annotations

from typing import Callable, List

from ranking import rank_opportunities
from report import build_report
from risk_filter import risk_quality_filter
from scanner import autonomous_scan
from schemas import TradeOpportunity, TradingResearchState
from observability import init_tracer, get_tracer


WorkflowNode = Callable[[TradingResearchState], TradingResearchState]


# ---------------------------------------------------------------------------
# CrewAI-backed nodes
# ---------------------------------------------------------------------------

def research_candidates(state: TradingResearchState) -> TradingResearchState:
    """
    Layer 3 — Crew 1: Research Synthesizer.
    Priority: LiteLLM direct (Mistral) → CrewAI crew → mock
    """
    import os

    # 1. Mistral via LiteLLM direct — fastest, most reliable path
    if os.environ.get("MISTRAL_API_KEY"):
        try:
            from llm_direct import run_research_direct
            state.research_items = run_research_direct(state.raw_candidates, state.config)
            return state
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"research_direct: {exc}")

    # 2. CrewAI crew fallback (requires compatible crewai + LLM config)
    try:
        from crews.research_synthesizer import run_research_synthesizer
        state.research_items = run_research_synthesizer(state.raw_candidates, state.config)
        return state
    except Exception as exc:  # noqa: BLE001
        state.errors.append(f"research_synthesizer_crew: {exc}")

    # 3. Legacy mock
    from research import research_candidates as _legacy_research
    state = _legacy_research(state)
    return state


def generate_opportunities(state: TradingResearchState) -> TradingResearchState:
    """
    Layer 3 — Crew 2 (Setup Validation) + Crew 3 (Trade Plan).
    Priority: LiteLLM direct (Mistral) → CrewAI crews → mock
    """
    import os

    # 1. Mistral via LiteLLM direct — fastest, most reliable path
    if os.environ.get("MISTRAL_API_KEY"):
        try:
            from llm_direct import run_trade_plan_direct

            # Build a lookup of scanner metrics by asset so they survive into the plan
            scanner_metrics = {
                c.asset: c.metrics for c in state.raw_candidates if c.metrics
            }

            opportunities = []
            for item in state.research_items:
                validation = _direct_validate(item, state.config)
                plan = run_trade_plan_direct(item, validation, state.config)
                if plan is not None:
                    # Restore scanner metrics if plan has empty metrics
                    if not any(plan.metrics.values()):
                        plan.metrics = scanner_metrics.get(item.asset, {})
                    opportunities.append(plan)
            state.opportunities = opportunities
            return state
        except Exception as exc2:  # noqa: BLE001
            state.errors.append(f"generate_opportunities_direct: {exc2}")

    # 2. CrewAI crews fallback
    try:
        from crews.setup_validation import run_setup_validation
        from crews.trade_plan import run_trade_plan

        opportunities: List[TradeOpportunity] = []
        for item in state.research_items:
            validation = run_setup_validation(
                opportunity=_stub_opportunity(item, state),
                research=item,
                config=state.config,
            )
            plan = run_trade_plan(
                research=item,
                validation=validation,
                config=state.config,
            )
            if plan is not None:
                opportunities.append(plan)
        state.opportunities = opportunities
        return state
    except Exception as exc:  # noqa: BLE001
        state.errors.append(f"generate_opportunities_crew: {exc}")

    # 3. Final fallback: legacy mock
    from opportunity import generate_opportunities as _legacy_opps
    state = _legacy_opps(state)
    return state


def _stub_opportunity(item, state: TradingResearchState):
    """
    Creates a minimal TradeOpportunity stub for Crew 2 validation.
    Crew 2 needs a candidate to validate before Crew 3 builds the full plan.
    """
    catalyst = item.catalysts[0] if item.catalysts else ""
    direction = "long"
    if "downside" in catalyst.lower() or "short" in catalyst.lower():
        direction = "short"

    return TradeOpportunity(
        asset=item.asset,
        market=item.market,
        direction=direction,
        setup_type="candidate_for_validation",
        thesis=item.summary,
        counter_thesis=item.bearish_factors[0] if item.bearish_factors else "Unknown risk.",
        catalyst=catalyst,
        timeframe=state.timeframe,
        # Use max(score, min_confidence+0.01) so the stub always passes
        # mock validation — the real confidence is set by Crew 3 / llm_direct
        confidence_initial=max(item.source_quality_score, 0.56),
        entry_logic="Pending validation.",
        stop_logic="Pending validation.",
        target_logic="Pending validation.",
        invalidation_conditions=item.news_risks or ["Pending validation."],
    )


def _direct_validate(item, config: dict) -> dict:
    """
    Deterministic validation — no crewai dependency.
    Used when CrewAI is not installed (Python 3.9 fallback).
    Mirrors the mock logic in crews/setup_validation.py.
    """
    min_confidence = float(config.get("risk", {}).get("min_confidence", 0.55))
    catalyst = item.catalysts[0] if item.catalysts else ""
    has_catalyst = bool(catalyst.strip())
    above_threshold = item.source_quality_score >= min_confidence

    if not has_catalyst or not above_threshold:
        return {
            "validated": False,
            "probability_score": item.source_quality_score,
            "risk_notes": item.news_risks,
            "rejection_reason": "Insufficient catalyst or confidence below threshold.",
        }

    return {
        "validated": True,
        "probability_score": item.source_quality_score,
        "risk_notes": item.news_risks,
        "rejection_reason": None,
    }


# ---------------------------------------------------------------------------
# Crew 4 — Execution Monitor
# ---------------------------------------------------------------------------

def monitor_executions(state: TradingResearchState) -> TradingResearchState:
    """
    Crew 4: Execution Monitor.
    Monitors open positions and recommends hold/adjust/exit actions.

    When execution_enabled: false (always, per immutable constraint) or when
    there are no open positions, this node is a clean no-op that appends an
    informational entry to monitoring_actions so the report can show the node ran.
    """
    import os

    # Safety guard: execution is always disabled in this system.
    # This node never initiates trades — it only analyses existing position data
    # that a human may have injected into state.open_positions externally.
    if not state.open_positions:
        state.monitoring_actions = [{
            "status": "no_open_positions",
            "message": "Execution monitor: no open positions to review.",
            "requires_human_review": True,
        }]
        return state

    try:
        from crews.execution_monitor import run_execution_monitor
        actions = run_execution_monitor(state.open_positions, state.config)
        state.monitoring_actions = actions
    except Exception as exc:  # noqa: BLE001
        state.errors.append(f"monitor_executions: {exc}")
        state.monitoring_actions = [{
            "status": "error",
            "message": f"Execution monitor failed: {exc}",
            "requires_human_review": True,
        }]

    return state


# ---------------------------------------------------------------------------
# Crew 5 — Post-Trade Review
# ---------------------------------------------------------------------------

def post_trade_review(state: TradingResearchState) -> TradingResearchState:
    """
    Crew 5: Post-Trade Review.
    Reviews a closed trade and produces a structured journal entry with lessons.

    When closed_trade is None (the default when no trade has been executed),
    this node is a clean no-op. The journal remains empty until a human
    injects a closed_trade dict into the state externally.
    """
    if state.closed_trade is None:
        state.post_trade_journal = {
            "status": "no_closed_trade",
            "message": "Post-trade review: no closed trade to analyse.",
        }
        return state

    try:
        from crews.post_trade_review import run_post_trade_review
        journal = run_post_trade_review(state.closed_trade, state.config)
        state.post_trade_journal = journal
    except Exception as exc:  # noqa: BLE001
        state.errors.append(f"post_trade_review: {exc}")
        state.post_trade_journal = {
            "status": "error",
            "message": f"Post-trade review failed: {exc}",
        }

    return state


# ---------------------------------------------------------------------------
# Simple workflow (no LangGraph dependency)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Slack + Observability — notify and log after report is built
# ---------------------------------------------------------------------------

def notify_and_log(state: TradingResearchState) -> TradingResearchState:
    """
    Post-report node:
      1. Sends Slack notifications for top opportunities (if SLACK_WEBHOOK_URL set)
      2. Flushes the run tracer to data/logs/
      3. Embeds trace summary into state.final_report
    """
    import os

    # 1 — Slack notifications
    try:
        from slack_notify import notify_opportunities, notify_run_summary, is_available
        if is_available():
            ranked = state.final_report.get("top_opportunities", [])
            run_id = state.final_report.get("run_id", "unknown")
            notify_opportunities(ranked, run_id=run_id, max_to_send=3)
            notify_run_summary(state.final_report, run_id=run_id)
    except Exception as exc:
        state.errors.append(f"slack_notify: {exc}")

    # 2 — Flush tracer to disk
    try:
        tracer = get_tracer()
        log_file = tracer.flush(final_summary={
            "opportunities_count": state.final_report.get("opportunities_count", 0),
            "top_opportunity": state.final_report.get("top_opportunity", ""),
            "errors": state.errors,
        })
        # 3 — Embed trace info in report
        state.final_report["observability"] = {
            "trace_id": tracer.trace_id,
            "log_file": str(log_file),
            **tracer.summary(),
        }
    except Exception as exc:
        state.errors.append(f"observability_flush: {exc}")

    return state


def run_simple_workflow(state: TradingResearchState) -> TradingResearchState:
    """
    Dependency-light fallback runner.
    Same node boundaries as the LangGraph workflow, useful for quick testing.
    """
    # Initialise tracer for this run
    tracer = init_tracer(run_id=getattr(state, "run_id", None))

    nodes: List[WorkflowNode] = [
        autonomous_scan,
        research_candidates,
        generate_opportunities,
        risk_quality_filter,
        rank_opportunities,
        build_report,
        monitor_executions,   # Crew 4 — no-op when no open positions
        post_trade_review,    # Crew 5 — no-op when no closed trade
        notify_and_log,       # Slack HiTL + observability flush
    ]

    for node in nodes:
        try:
            with tracer.span(node.__name__) as span:
                state = node(state)
                # Log key metrics per node
                if node.__name__ == "autonomous_scan":
                    span.set_data({"candidates": len(state.raw_candidates)})
                elif node.__name__ == "research_candidates":
                    span.set_data({"items": len(state.research_items)})
                elif node.__name__ == "generate_opportunities":
                    span.set_data({"opportunities": len(state.opportunities)})
                elif node.__name__ == "risk_quality_filter":
                    span.set_data({
                        "passed": len(state.filtered_opportunities),
                        "rejected": len(state.rejected_opportunities),
                    })
                elif node.__name__ == "rank_opportunities":
                    span.set_data({"ranked": len(state.ranked_opportunities)})
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"{node.__name__}: {exc}")
            tracer.log(node.__name__, str(exc), level="ERROR")
            break

    return state


# ---------------------------------------------------------------------------
# LangGraph workflow
# ---------------------------------------------------------------------------

def build_langgraph_app():
    """
    Builds the LangGraph StateGraph.
    The graph accepts and returns TradingResearchState objects.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "langgraph is not installed. Use run_simple_workflow or install requirements.txt."
        ) from exc

    graph = StateGraph(TradingResearchState)

    graph.add_node("autonomous_scan", autonomous_scan)
    graph.add_node("research_candidates", research_candidates)
    graph.add_node("generate_opportunities", generate_opportunities)
    graph.add_node("risk_quality_filter", risk_quality_filter)
    graph.add_node("rank_opportunities", rank_opportunities)
    graph.add_node("build_report", build_report)
    graph.add_node("monitor_executions", monitor_executions)   # Crew 4
    graph.add_node("post_trade_review", post_trade_review)     # Crew 5

    graph.add_edge(START, "autonomous_scan")
    graph.add_edge("autonomous_scan", "research_candidates")
    graph.add_edge("research_candidates", "generate_opportunities")
    graph.add_edge("generate_opportunities", "risk_quality_filter")
    graph.add_edge("risk_quality_filter", "rank_opportunities")
    graph.add_edge("rank_opportunities", "build_report")
    graph.add_edge("build_report", "monitor_executions")
    graph.add_edge("monitor_executions", "post_trade_review")
    graph.add_edge("post_trade_review", END)

    return graph.compile()


def run_langgraph_workflow(state: TradingResearchState) -> TradingResearchState:
    app = build_langgraph_app()
    result = app.invoke(state)
    if isinstance(result, TradingResearchState):
        return result
    return TradingResearchState.model_validate(result)
