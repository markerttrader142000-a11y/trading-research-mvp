"""
src/trading_research/flow.py
─────────────────────────────────────────────────────────────
CrewAI Flow — pipeline completo de research.

Estrutura:
  scan_market          → cTrader / Alpaca / mock
      ↓
  research_candidates  → ResearchSynthesizerCrew (Crew 1)
      ↓
  generate_plans       → SetupValidationCrew (Crew 2) + TradePlanCrew (Crew 3)
      ↓
  filter_and_rank      → risk_filter.py + ranking.py (determinístico)
      ↓
  build_report         → report.py
      ↓
  monitor_positions    → ExecutionMonitorCrew (Crew 4) — no-op se vazio
      ↓
  review_closed_trade  → PostTradeReviewCrew (Crew 5) — no-op se None

IMUTÁVEL: execution_enabled: false em todo o flow.
Nenhum nó envia ordens. Todos os TradeOpportunity têm requires_human_approval: true.

Uso local:
  python -m src.trading_research.flow

Uso como entrypoint CrewAI:
  from src.trading_research.flow import TradingResearchFlow
  TradingResearchFlow().kickoff()
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from crewai.flow.flow import Flow, listen, start

# ── Lazy imports (evitar erros quando pacotes opcionais não estão instalados)
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
    except ImportError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Flow State (Pydantic v2, compatible com CrewAI Flow)
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from uuid import uuid4
from datetime import datetime, timezone


class TradingFlowState(BaseModel):
    """Estado partilhado entre todos os steps do Flow."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    # Config carregada no início
    config: Dict[str, Any] = Field(default_factory=dict)

    # Pipeline intermediário
    raw_candidates: List[Dict] = Field(default_factory=list)
    research_items: List[Dict] = Field(default_factory=list)
    opportunities: List[Dict] = Field(default_factory=list)
    filtered_opportunities: List[Dict] = Field(default_factory=list)
    ranked_opportunities: List[Dict] = Field(default_factory=list)

    # Relatório final
    final_report: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

    # Crew 4 — injectado externamente por humano quando há posições abertas
    open_positions: List[Dict] = Field(default_factory=list)
    monitoring_actions: List[Dict] = Field(default_factory=list)

    # Crew 5 — injectado externamente por humano após fechar um trade
    closed_trade: Optional[Dict] = None
    post_trade_journal: Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Flow
# ─────────────────────────────────────────────────────────────────────────────

class TradingResearchFlow(Flow[TradingFlowState]):
    """
    Pipeline de research autónomo — sem execução de ordens.
    Gera uma watchlist rankeada para revisão humana.
    """

    # ── Step 1: Carregar config e fazer scan ─────────────────────────────────

    @start()
    def scan_market(self) -> None:
        """Carrega config e faz scan ao mercado (cTrader / Alpaca / mock)."""
        _load_env()

        # Carregar config
        try:
            from config import load_config
            self.state.config = load_config(None)
        except Exception as exc:
            self.state.errors.append(f"config_load: {exc}")
            self.state.config = {}

        # Correr scanner — importa o TradingResearchState do pipeline existente
        try:
            from schemas import TradingResearchState
            from scanner import autonomous_scan

            cfg = self.state.config
            pipeline_state = TradingResearchState(
                markets=cfg.get("markets", ["forex"]),
                timeframe=cfg.get("timeframe", "H1"),
                max_candidates=int(cfg.get("max_candidates", 10)),
                max_final_opportunities=int(cfg.get("max_final_opportunities", 5)),
                config=cfg,
            )
            pipeline_state = autonomous_scan(pipeline_state)
            self.state.raw_candidates = [c.model_dump() for c in pipeline_state.raw_candidates]
            self.state.errors.extend(pipeline_state.errors)
        except Exception as exc:
            self.state.errors.append(f"scan_market: {exc}")

    # ── Step 2: Research (Crew 1) ─────────────────────────────────────────────

    @listen(scan_market)
    def research_candidates(self) -> None:
        """Research de cada candidato — Mistral direct → Crew 1 → mock."""
        if not self.state.raw_candidates:
            return

        try:
            from schemas import MarketCandidate, TradingResearchState
            from graph import research_candidates as _research_node

            cfg = self.state.config
            pipeline_state = TradingResearchState(
                markets=cfg.get("markets", ["forex"]),
                timeframe=cfg.get("timeframe", "H1"),
                max_candidates=int(cfg.get("max_candidates", 10)),
                max_final_opportunities=int(cfg.get("max_final_opportunities", 5)),
                config=cfg,
                raw_candidates=[MarketCandidate(**c) for c in self.state.raw_candidates],
            )
            pipeline_state = _research_node(pipeline_state)
            self.state.research_items = [r.model_dump() for r in pipeline_state.research_items]
            self.state.errors.extend(pipeline_state.errors)
        except Exception as exc:
            self.state.errors.append(f"research_candidates: {exc}")

    # ── Step 3: Trade Plans (Crew 2 + 3) ─────────────────────────────────────

    @listen(research_candidates)
    def generate_plans(self) -> None:
        """Gera planos de trade — Mistral direct → Crew 2+3 → mock."""
        if not self.state.research_items:
            return

        try:
            from schemas import MarketCandidate, ResearchItem, TradingResearchState
            from graph import generate_opportunities as _opps_node

            cfg = self.state.config
            pipeline_state = TradingResearchState(
                markets=cfg.get("markets", ["forex"]),
                timeframe=cfg.get("timeframe", "H1"),
                max_candidates=int(cfg.get("max_candidates", 10)),
                max_final_opportunities=int(cfg.get("max_final_opportunities", 5)),
                config=cfg,
                raw_candidates=[MarketCandidate(**c) for c in self.state.raw_candidates],
                research_items=[ResearchItem(**r) for r in self.state.research_items],
            )
            pipeline_state = _opps_node(pipeline_state)
            self.state.opportunities = [o.model_dump() for o in pipeline_state.opportunities]
            self.state.errors.extend(pipeline_state.errors)
        except Exception as exc:
            self.state.errors.append(f"generate_plans: {exc}")

    # ── Step 4: Filter + Rank (determinístico) ────────────────────────────────

    @listen(generate_plans)
    def filter_and_rank(self) -> None:
        """Risk filter + ranking — sem LLM, determinístico."""
        if not self.state.opportunities:
            return

        try:
            from schemas import (MarketCandidate, ResearchItem,
                                 TradeOpportunity, TradingResearchState)
            from risk_filter import risk_quality_filter
            from ranking import rank_opportunities

            cfg = self.state.config
            pipeline_state = TradingResearchState(
                markets=cfg.get("markets", ["forex"]),
                timeframe=cfg.get("timeframe", "H1"),
                max_candidates=int(cfg.get("max_candidates", 10)),
                max_final_opportunities=int(cfg.get("max_final_opportunities", 5)),
                config=cfg,
                raw_candidates=[MarketCandidate(**c) for c in self.state.raw_candidates],
                research_items=[ResearchItem(**r) for r in self.state.research_items],
                opportunities=[TradeOpportunity(**o) for o in self.state.opportunities],
            )
            pipeline_state = risk_quality_filter(pipeline_state)
            pipeline_state = rank_opportunities(pipeline_state)
            self.state.filtered_opportunities = [
                f.model_dump() for f in pipeline_state.filtered_opportunities
            ]
            self.state.ranked_opportunities = [
                r.model_dump() for r in pipeline_state.ranked_opportunities
            ]
            self.state.errors.extend(pipeline_state.errors)
        except Exception as exc:
            self.state.errors.append(f"filter_and_rank: {exc}")

    # ── Step 5: Build Report ──────────────────────────────────────────────────

    @listen(filter_and_rank)
    def build_report(self) -> None:
        """Monta o relatório final JSON."""
        try:
            from schemas import (MarketCandidate, RankedOpportunity,
                                 ResearchItem, RiskCheckedOpportunity,
                                 TradeOpportunity, TradingResearchState)
            from report import build_report as _build

            cfg = self.state.config
            pipeline_state = TradingResearchState(
                run_id=self.state.run_id,
                scan_date=self.state.scan_date,
                markets=cfg.get("markets", ["forex"]),
                timeframe=cfg.get("timeframe", "H1"),
                max_candidates=int(cfg.get("max_candidates", 10)),
                max_final_opportunities=int(cfg.get("max_final_opportunities", 5)),
                config=cfg,
                raw_candidates=[MarketCandidate(**c) for c in self.state.raw_candidates],
                research_items=[ResearchItem(**r) for r in self.state.research_items],
                opportunities=[TradeOpportunity(**o) for o in self.state.opportunities],
                ranked_opportunities=[
                    RankedOpportunity(**r) for r in self.state.ranked_opportunities
                ],
                errors=list(self.state.errors),
            )
            pipeline_state = _build(pipeline_state)
            self.state.final_report = pipeline_state.final_report
        except Exception as exc:
            self.state.errors.append(f"build_report: {exc}")

    # ── Step 6: Execution Monitor (Crew 4) — no-op por defeito ───────────────

    @listen(build_report)
    def monitor_positions(self) -> None:
        """
        Crew 4: Execution Monitor.
        No-op quando open_positions está vazio (execution_enabled: false).
        Para activar: injectar open_positions no estado antes do kickoff.
        """
        if not self.state.open_positions:
            self.state.monitoring_actions = [{
                "status": "no_open_positions",
                "message": "Execution monitor: no open positions to review.",
                "requires_human_review": True,
            }]
            return

        try:
            from crews.execution_monitor import run_execution_monitor
            self.state.monitoring_actions = run_execution_monitor(
                self.state.open_positions, self.state.config
            )
        except Exception as exc:
            self.state.errors.append(f"monitor_positions: {exc}")
            self.state.monitoring_actions = [{
                "status": "error",
                "message": f"Monitor failed: {exc}",
                "requires_human_review": True,
            }]

    # ── Step 7: Post-Trade Review (Crew 5) — no-op por defeito ───────────────

    @listen(monitor_positions)
    def review_closed_trade(self) -> None:
        """
        Crew 5: Post-Trade Review.
        No-op quando closed_trade is None.
        Para activar: injectar closed_trade no estado antes do kickoff.
        """
        if self.state.closed_trade is None:
            self.state.post_trade_journal = {
                "status": "no_closed_trade",
                "message": "Post-trade review: no closed trade to analyse.",
            }
            return

        try:
            from crews.post_trade_review import run_post_trade_review
            self.state.post_trade_journal = run_post_trade_review(
                self.state.closed_trade, self.state.config
            )
        except Exception as exc:
            self.state.errors.append(f"review_closed_trade: {exc}")
            self.state.post_trade_journal = {
                "status": "error",
                "message": f"Post-trade review failed: {exc}",
            }


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def run() -> None:
    """Entrypoint: python -m src.trading_research.flow"""
    _load_env()

    # Adicionar o root do projecto ao sys.path para imports relativos
    import sys
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    flow = TradingResearchFlow()
    flow.kickoff()

    # Output JSON (compatível com main.py > report.json)
    print(json.dumps(flow.state.final_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
