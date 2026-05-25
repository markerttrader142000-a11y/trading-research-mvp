"""
src/trading_research_mvp/main.py
─────────────────────────────────────────────────────────────
Entrypoint required by CrewAI deploy for Flow projects.
CrewAI platform looks for a Flow subclass in this file.

The actual implementation lives in flow.py — this file just
re-exports TradingResearchFlow so the platform can discover it.

IMUTÁVEL: execution_enabled: false — research only.
"""
from src.trading_research_mvp.flow import TradingResearchFlow  # noqa: F401

# CrewAI platform instantiates the Flow with no arguments.
# TradingResearchFlow() is already safe to call with no args.

def run() -> None:
    """Entrypoint for `crewai run`."""
    flow = TradingResearchFlow()
    flow.kickoff()


if __name__ == "__main__":
    run()
