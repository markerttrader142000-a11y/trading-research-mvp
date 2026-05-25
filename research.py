from __future__ import annotations

from typing import List

from schemas import ResearchItem, TradingResearchState


def research_candidates(state: TradingResearchState) -> TradingResearchState:
    """
    MVP research node.

    Mock research keeps citations as placeholders. In production, replace this
    with Perplexity/API calls and store real source URLs.
    """
    research_items: List[ResearchItem] = []

    for candidate in state.raw_candidates:
        if candidate.market == "ctrader":
            research_items.append(
                ResearchItem(
                    asset=candidate.asset,
                    market=candidate.market,
                    summary=(
                        f"{candidate.asset} was selected from cTrader trendbar data. "
                        "This is price-action-only research without external news context."
                    ),
                    bullish_factors=[
                        "Recent trendbar movement may indicate short-term momentum.",
                        "The symbol passed configured movement/range thresholds.",
                    ],
                    bearish_factors=[
                        "Price-action-only signals can be false breakouts.",
                        "No macro/news filter is connected yet.",
                    ],
                    catalysts=[candidate.reason],
                    macro_events=[],
                    news_risks=["External news and calendar risk not connected in this version."],
                    sources=[candidate.source_hint or "cTrader Open API trendbars"],
                    source_quality_score=min(0.95, 0.65 + float(candidate.metrics.get("scan_score", 0)) / 10),
                )
            )
        elif candidate.market == "stocks":
            research_items.append(
                ResearchItem(
                    asset=candidate.asset,
                    market=candidate.market,
                    summary=(
                        f"{candidate.asset} was selected by the Alpaca scanner based on recent price movement. "
                        "This is market-data-driven only and does not include news or fundamental context yet."
                    ),
                    bullish_factors=[
                        "Recent price momentum may indicate institutional attention or short-term continuation.",
                        "The candidate passed the configured movement threshold.",
                    ],
                    bearish_factors=[
                        "Price movement alone is not a complete catalyst.",
                        "Requires chart validation and news check before any real trade decision.",
                    ],
                    catalysts=[candidate.reason],
                    macro_events=[],
                    news_risks=["News context not connected in this version."],
                    sources=[candidate.source_hint or "Alpaca historical stock bars"],
                    source_quality_score=0.72,
                )
            )
        elif candidate.asset == "EUR/USD":
            research_items.append(
                ResearchItem(
                    asset=candidate.asset,
                    market=candidate.market,
                    summary="EUR/USD is sensitive to central-bank expectations, inflation data, and USD momentum.",
                    bullish_factors=[
                        "Potential EUR support if European data surprises positively.",
                        "Potential USD weakness if US data lowers rate expectations.",
                    ],
                    bearish_factors=[
                        "USD strength can invalidate the long thesis quickly.",
                        "Event risk can trigger whipsaw price action.",
                    ],
                    catalysts=["Upcoming macro data and central-bank repricing."],
                    macro_events=["US and Eurozone macro releases."],
                    news_risks=["High volatility around data releases."],
                    sources=["MOCK_SOURCE: replace with Perplexity citations"],
                    source_quality_score=0.65,
                )
            )
        elif candidate.asset == "Gold":
            research_items.append(
                ResearchItem(
                    asset=candidate.asset,
                    market=candidate.market,
                    summary="Gold is driven by real yields, USD direction, inflation expectations, and risk sentiment.",
                    bullish_factors=[
                        "Safe-haven bid can support gold during risk-off periods.",
                        "Lower yields or weaker USD can support upside.",
                    ],
                    bearish_factors=[
                        "Higher real yields can pressure gold.",
                        "Strong USD can reduce upside potential.",
                    ],
                    catalysts=["Rates expectations and risk sentiment."],
                    macro_events=["US yields, inflation data, central-bank commentary."],
                    news_risks=["Sharp reversals around macro headlines."],
                    sources=["MOCK_SOURCE: replace with Perplexity citations"],
                    source_quality_score=0.6,
                )
            )
        else:
            research_items.append(
                ResearchItem(
                    asset=candidate.asset,
                    market=candidate.market,
                    summary="NASDAQ 100 depends on growth sentiment, rates, earnings revisions, and mega-cap technology flows.",
                    bullish_factors=[
                        "Momentum can continue if risk appetite remains strong.",
                        "Lower yields can support long-duration equity multiples.",
                    ],
                    bearish_factors=[
                        "Rate shock can pressure valuations.",
                        "Concentration risk can amplify downside.",
                    ],
                    catalysts=["Risk sentiment, rates, and large-cap technology momentum."],
                    macro_events=["US rates, inflation expectations, tech earnings headlines."],
                    news_risks=["Index can reverse sharply if yields rise."],
                    sources=["MOCK_SOURCE: replace with Perplexity citations"],
                    source_quality_score=0.58,
                )
            )

    state.research_items = research_items
    return state
