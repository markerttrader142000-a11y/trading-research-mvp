from __future__ import annotations

from typing import List

from schemas import RejectedOpportunity, RiskCheckedOpportunity, TradingResearchState


def risk_quality_filter(state: TradingResearchState) -> TradingResearchState:
    risk_config = state.config.get("risk", {})
    min_confidence = float(risk_config.get("min_confidence", 0.55))
    min_rr = float(risk_config.get("min_rr", 1.5))

    approved: List[RiskCheckedOpportunity] = []
    rejected: List[RejectedOpportunity] = []
    source_quality_by_asset = {
        item.asset: item.source_quality_score for item in state.research_items
    }

    for opp in state.opportunities:
        checks: List[str] = []

        if opp.direction == "neutral":
            checks.append("Sem direção clara")

        if not opp.catalyst:
            checks.append("Sem catalyst claro")

        if not opp.invalidation_conditions:
            checks.append("Sem condições de invalidação")

        if opp.confidence_initial < min_confidence:
            checks.append(f"Confiança abaixo do mínimo ({opp.confidence_initial:.2f} < {min_confidence:.2f})")

        if checks:
            rejected.append(
                RejectedOpportunity(
                    asset=opp.asset,
                    reason="; ".join(checks),
                    stage="risk_quality_filter",
                )
            )
            continue

        approved.append(
            RiskCheckedOpportunity(
                opportunity=opp,
                source_quality_score=source_quality_by_asset.get(opp.asset, 0.0),
                quality_status="approved_for_review",
                risk_status="requires_manual_review",
                min_rr_required=min_rr,
                risk_notes=[
                    "Execução automática desativada.",
                    "Requer validação visual do gráfico.",
                    "Requer aprovação humana antes de qualquer trade real.",
                ],
            )
        )

    state.filtered_opportunities = approved
    state.rejected_opportunities = rejected
    return state
