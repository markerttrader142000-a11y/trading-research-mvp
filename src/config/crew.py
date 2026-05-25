"""
src/config/crew.py — CrewAI Studio crew configuration
-------------------------------------------------------
Required by the CrewAI platform deployment system.

This file registers the TradingResearchCrew as the main crew
for this project.

IMMUTABLE CONSTRAINT:
  execution_enabled: false — research only, never order execution.
  requires_human_approval: true — on every TradeOpportunity, always.
"""
from src.crew import TradingResearchCrew

# The crew instance the platform will use
crew = TradingResearchCrew().crew()
