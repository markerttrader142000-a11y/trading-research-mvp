from __future__ import annotations

from schemas import TradingResearchState


def _data_provider_status(config: dict) -> dict:
    """Lazy wrapper — market_data may not be importable in all environments."""
    try:
        from market_data import get_data_provider_status
        return get_data_provider_status(config)
    except Exception:  # noqa: BLE001
        return {"provider": config.get("data", {}).get("provider", "unknown")}


def build_report(state: TradingResearchState) -> TradingResearchState:
    top = state.ranked_opportunities[: state.max_final_opportunities]

    state.final_report = {
        "run_id": state.run_id,
        "scan_date": state.scan_date,
        "generated_at": state.scan_date,
        "opportunities_count": len(top),
        "top_opportunity": top[0].opportunity.asset if top else None,
        "mode": "autonomous_research_no_execution",
        "data_provider": {
            **_data_provider_status(state.config),
            "runtime_provider_used": state.config.get("_runtime", {}).get("provider_used"),
            "ctrader_selected_period": state.config.get("_runtime", {}).get("ctrader_selected_period"),
            "ctrader_period_summaries": state.config.get("_runtime", {}).get("ctrader_period_summaries"),
        },
        "markets": state.markets,
        "timeframe": state.timeframe,
        "summary": {
            "raw_candidates": len(state.raw_candidates),
            "researched": len(state.research_items),
            "generated_opportunities": len(state.opportunities),
            "approved_for_review": len(state.filtered_opportunities),
            "rejected": len(state.rejected_opportunities),
        },
        "top_opportunities": [item.model_dump() for item in top],
        "rejected": [item.model_dump() for item in state.rejected_opportunities],
        "rules": {
            "execution_enabled": False,
            "human_approval_required": True,
            "chart_validation_required": True,
            "note": "MVP gera oportunidades para revisão. Não envia ordens.",
        },
        "monitoring": {
            "open_positions_count": len(state.open_positions),
            "actions": state.monitoring_actions,
        },
        "post_trade_journal": state.post_trade_journal,
        "errors": state.errors,
    }

    return state
