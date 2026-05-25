from __future__ import annotations

from typing import List

from schemas import TradeOpportunity, TradingResearchState


def generate_opportunities(state: TradingResearchState) -> TradingResearchState:
    """
    Converts research into candidate trade opportunities.

    In production, this can call Claude/OpenAI/Gemini and request strict JSON.
    """
    opportunities: List[TradeOpportunity] = []

    for item in state.research_items:
        if item.market == "ctrader":
            direction = "long"
            if "downside momentum" in item.catalysts[0].lower():
                direction = "short"
            metrics = _parse_ctrader_metrics_from_catalyst(item.catalysts[0])
            confidence = min(0.78, 0.52 + abs(metrics.get("move_pct", 0.0)) * 0.08 + metrics.get("range_pct", 0.0) * 0.04)
            opportunities.append(
                TradeOpportunity(
                    asset=item.asset,
                    market=item.market,
                    direction=direction,
                    setup_type="ctrader_price_action_watchlist",
                    thesis=(
                        f"{item.asset} is a cTrader watchlist candidate because recent trendbars show directional movement. "
                        "This is a technical candidate, not a final trade signal."
                    ),
                    counter_thesis=(
                        "The move may be exhausted or caused by temporary volatility; external news is not checked yet."
                    ),
                    catalyst=item.catalysts[0],
                    timeframe="intraday_or_swing",
                    confidence_initial=round(confidence, 3),
                    entry_logic="Wait for chart confirmation in the scan direction before considering entry.",
                    stop_logic="Invalidate if price reverses through the recent structure or if spread/volatility becomes abnormal.",
                    target_logic="Only consider if nearby structure allows at least 1.5R.",
                    invalidation_conditions=[
                        "No clean continuation or pullback structure.",
                        "Spread widens materially.",
                        "Upcoming macro/news event conflicts with direction.",
                    ],
                    metrics=metrics,
                )
            )
        elif item.market == "stocks":
            direction = "long"
            if "downside momentum" in item.catalysts[0].lower():
                direction = "short"
            opportunities.append(
                TradeOpportunity(
                    asset=item.asset,
                    market=item.market,
                    direction=direction,
                    setup_type="price_momentum_watchlist",
                    thesis=(
                        f"{item.asset} is a watchlist candidate because recent Alpaca bar data shows notable movement. "
                        "This is a quantitative scan candidate, not a complete trade signal."
                    ),
                    counter_thesis=(
                        "Momentum may be exhausted, headline-driven, or unsupported by broader market context."
                    ),
                    catalyst=item.catalysts[0],
                    timeframe="intraday_or_swing",
                    confidence_initial=0.58,
                    entry_logic="Wait for chart confirmation in the direction of the scan before considering entry.",
                    stop_logic="Invalidate if price reverses through the confirmation structure or volatility becomes abnormal.",
                    target_logic="Only consider if a technical target offers at least 1.5R.",
                    invalidation_conditions=[
                        "No clean chart confirmation.",
                        "Move appears extended without consolidation.",
                        "News or market context contradicts the direction.",
                    ],
                )
            )
        elif item.asset == "EUR/USD":
            opportunities.append(
                TradeOpportunity(
                    asset=item.asset,
                    market=item.market,
                    direction="long",
                    setup_type="macro_momentum",
                    thesis="EUR/USD may offer a long watchlist setup if USD weakens after macro repricing.",
                    counter_thesis="The setup fails if US data strengthens USD or if risk-off demand supports the dollar.",
                    catalyst=item.catalysts[0],
                    timeframe="intraday_or_swing",
                    confidence_initial=0.64,
                    entry_logic="Wait for chart confirmation above a relevant intraday resistance or reclaim zone.",
                    stop_logic="Invalidate below the confirmation zone or if the macro catalyst turns USD-positive.",
                    target_logic="Target the next resistance area, requiring at least 1.5R before consideration.",
                    invalidation_conditions=[
                        "Stronger-than-expected US macro data.",
                        "Failure to hold above confirmation level.",
                        "Spread or volatility becomes abnormal around news.",
                    ],
                )
            )
        elif item.asset == "Gold":
            opportunities.append(
                TradeOpportunity(
                    asset=item.asset,
                    market=item.market,
                    direction="neutral",
                    setup_type="macro_volatility_watch",
                    thesis="Gold may move strongly if yields or USD break directionally.",
                    counter_thesis="Current setup is not directional enough without confirmation from yields/USD.",
                    catalyst=item.catalysts[0],
                    timeframe="intraday_or_swing",
                    confidence_initial=0.49,
                    entry_logic="No entry until a clear directional break is visible.",
                    stop_logic="No stop can be defined before direction is selected.",
                    target_logic="Only valid after directional confirmation.",
                    invalidation_conditions=[],
                )
            )
        else:
            opportunities.append(
                TradeOpportunity(
                    asset=item.asset,
                    market=item.market,
                    direction="short",
                    setup_type="risk_sentiment_reversal",
                    thesis="NASDAQ 100 may offer a short watchlist setup if yields rise and risk appetite weakens.",
                    counter_thesis="Momentum remains strong and dip-buying can invalidate bearish setups.",
                    catalyst=item.catalysts[0],
                    timeframe="intraday_or_swing",
                    confidence_initial=0.57,
                    entry_logic="Wait for rejection from resistance or confirmed breakdown below intraday support.",
                    stop_logic="Invalidate above the rejection high or if risk sentiment recovers strongly.",
                    target_logic="Target next support, requiring at least 1.5R.",
                    invalidation_conditions=[
                        "Yields fall and technology momentum strengthens.",
                        "Price reclaims rejected resistance.",
                    ],
                )
            )

    state.opportunities = opportunities
    return state


def _parse_ctrader_metrics_from_catalyst(catalyst: str) -> dict:
    import re

    def find(pattern: str) -> float:
        match = re.search(pattern, catalyst)
        if not match:
            return 0.0
        return float(match.group(1))

    period_match = re.search(r"period=([A-Z0-9]+)", catalyst)
    return {
        "move_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback move"),
        "last_bar_move_pct": find(r"([-+]?\d+(?:\.\d+)?)% last-bar move"),
        "range_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback range"),
        "period": period_match.group(1) if period_match else None,
    }
