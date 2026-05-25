from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MarketCandidate(BaseModel):
    asset: str
    market: str
    reason: str
    catalyst_type: Optional[str] = None
    timeframe: str
    source_hint: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ResearchItem(BaseModel):
    asset: str
    market: str
    summary: str
    bullish_factors: List[str] = Field(default_factory=list)
    bearish_factors: List[str] = Field(default_factory=list)
    catalysts: List[str] = Field(default_factory=list)
    macro_events: List[str] = Field(default_factory=list)
    news_risks: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    source_quality_score: float = 0.0


class TradeOpportunity(BaseModel):
    asset: str
    market: str
    direction: Literal["long", "short", "neutral"]
    setup_type: str
    thesis: str
    counter_thesis: str
    catalyst: str
    timeframe: str
    confidence_initial: float
    entry_logic: str
    stop_logic: str
    target_logic: str
    invalidation_conditions: List[str] = Field(default_factory=list)
    requires_chart_validation: bool = True
    requires_human_approval: bool = True
    metrics: Dict[str, Any] = Field(default_factory=dict)


class RejectedOpportunity(BaseModel):
    asset: str
    reason: str
    stage: str


class RiskCheckedOpportunity(BaseModel):
    opportunity: TradeOpportunity
    source_quality_score: float
    quality_status: Literal["approved_for_review", "rejected", "needs_more_data"]
    risk_status: Literal["ok", "too_unclear", "too_risky", "requires_manual_review"]
    min_rr_required: float
    risk_notes: List[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None


class RankedOpportunity(BaseModel):
    opportunity: TradeOpportunity
    score: float
    rank: int
    decision: Literal["watch_for_entry", "review_manually", "reject"]
    why: str


class TradingResearchState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    markets: List[str]
    timeframe: str
    max_candidates: int
    max_final_opportunities: int = 5
    config: Dict[str, Any] = Field(default_factory=dict)

    raw_candidates: List[MarketCandidate] = Field(default_factory=list)
    research_items: List[ResearchItem] = Field(default_factory=list)
    opportunities: List[TradeOpportunity] = Field(default_factory=list)
    filtered_opportunities: List[RiskCheckedOpportunity] = Field(default_factory=list)
    rejected_opportunities: List[RejectedOpportunity] = Field(default_factory=list)
    ranked_opportunities: List[RankedOpportunity] = Field(default_factory=list)

    final_report: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

    # Crew 4 — Execution Monitor (runs with empty data when execution_enabled: false)
    open_positions: List[Dict[str, Any]] = Field(default_factory=list)
    monitoring_actions: List[Dict[str, Any]] = Field(default_factory=list)

    # Crew 5 — Post-Trade Review (runs with empty data when no closed trade)
    closed_trade: Optional[Dict[str, Any]] = None
    post_trade_journal: Dict[str, Any] = Field(default_factory=dict)
