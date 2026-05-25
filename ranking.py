from __future__ import annotations

from typing import List

from schemas import RankedOpportunity, TradingResearchState


def rank_opportunities(state: TradingResearchState) -> TradingResearchState:
    ranked: List[RankedOpportunity] = []

    for item in state.filtered_opportunities:
        opp = item.opportunity
        metrics = opp.metrics or {}

        move_pct = abs(float(metrics.get("move_pct", 0.0)))
        last_bar_move_pct = float(metrics.get("last_bar_move_pct", 0.0))
        range_pct = float(metrics.get("range_pct", 0.0))
        overall_move = float(metrics.get("move_pct", 0.0))

        # Base scores
        catalyst_score = 2.0 if opp.catalyst else 0.0
        clarity_score = 2.0 if opp.entry_logic and opp.stop_logic and opp.target_logic else 0.0
        confidence_score = opp.confidence_initial * 3.0
        source_score = item.source_quality_score * 2.0

        # cTrader metrics scores — amplified to create real differentiation
        move_score = min(2.0, move_pct * 3.0)       # max 2.0 pts, reached at ~0.67% move
        range_score = min(1.5, range_pct * 0.6)     # max 1.5 pts, reached at ~2.5% range

        # Penalty: last bar contradicts overall direction (momentum fading/reversing)
        last_bar_penalty = 0.0
        if overall_move != 0.0 and last_bar_move_pct != 0.0:
            if overall_move * last_bar_move_pct < 0:
                last_bar_penalty = 0.5  # stronger penalty for clear contradiction

        # Standard execution caution penalties (same for all cTrader)
        chart_penalty = 0.5 if opp.requires_chart_validation else 0.0
        manual_penalty = 0.25 if opp.requires_human_approval else 0.0

        score = (
            confidence_score
            + source_score
            + catalyst_score
            + clarity_score
            + move_score
            + range_score
            - last_bar_penalty
            - chart_penalty
            - manual_penalty
        )

        # Build a dynamic explanation
        why_parts = []
        if move_pct >= 0.3:
            why_parts.append(f"movimento forte ({move_pct:.3f}%)")
        elif move_pct > 0:
            why_parts.append(f"movimento fraco ({move_pct:.3f}%)")
        if range_pct >= 1.0:
            why_parts.append(f"range amplo ({range_pct:.3f}%)")
        if last_bar_penalty > 0:
            why_parts.append("último candle contra a direção (penalização)")
        if not why_parts:
            why_parts.append("candidato técnico básico")
        why = "Watchlist: " + "; ".join(why_parts) + ". Pendente validação humana/gráfico."

        decision = "watch_for_entry" if score >= 7.0 else "review_manually"

        ranked.append(
            RankedOpportunity(
                opportunity=opp,
                score=round(score, 2),
                rank=0,
                decision=decision,
                why=why,
            )
        )

    ranked = sorted(ranked, key=lambda item: item.score, reverse=True)
    for index, item in enumerate(ranked, start=1):
        item.rank = index

    state.ranked_opportunities = ranked
    return state
