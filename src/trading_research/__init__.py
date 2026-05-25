"""
Trading Research MVP — CrewAI package.

Entrypoints:
  flow  → TradingResearchFlow (CrewAI Flow, recomendado)
  crew  → 5 crews individuais (ResearchSynthesizerCrew, etc.)
"""
from src.trading_research.crew import (
    ExecutionMonitorCrew,
    PostTradeReviewCrew,
    ResearchSynthesizerCrew,
    SetupValidationCrew,
    TradePlanCrew,
)
from src.trading_research.flow import TradingResearchFlow

__all__ = [
    "TradingResearchFlow",
    "ResearchSynthesizerCrew",
    "SetupValidationCrew",
    "TradePlanCrew",
    "ExecutionMonitorCrew",
    "PostTradeReviewCrew",
]
