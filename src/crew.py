"""
src/crew.py — CrewAI Studio entry point
----------------------------------------
This wraps the Trading Research MVP crews for deployment in CrewAI Studio.

The project has 3 active crews:
  Crew 1 — Research Synthesizer  (crews/research_synthesizer.py)
  Crew 2 — Setup Validation       (crews/setup_validation.py)
  Crew 3 — Trade Plan             (crews/trade_plan.py)

IMMUTABLE CONSTRAINT:
  execution_enabled: false — this is research only, never order execution.
  requires_human_approval: true — on every TradeOpportunity, always.
"""
from __future__ import annotations

import os
import sys

# Ensure the project root is on the path so we can import crews/agents/schemas
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from agents.llm_factory import make_llm


@CrewBase
class TradingResearchCrew:
    """
    Trading Research Crew — Research Synthesizer (Crew 1)

    Purpose: Analyse market candidates and produce structured ResearchItem outputs.
    Uses Mistral AI via LiteLLM.

    SAFETY: This crew does NOT execute trades. Output is a research watchlist only.
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self):
        self.llm = make_llm("mistral")

    @agent
    def macro_research_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["macro_research_analyst"],  # type: ignore
            llm=self.llm,
            verbose=True,
        )

    @agent
    def market_context_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["market_context_analyst"],  # type: ignore
            llm=self.llm,
            verbose=True,
        )

    @agent
    def contrarian_checker(self) -> Agent:
        return Agent(
            config=self.agents_config["contrarian_checker"],  # type: ignore
            llm=self.llm,
            verbose=True,
        )

    @task
    def macro_research_task(self) -> Task:
        return Task(
            config=self.tasks_config["macro_research_task"],  # type: ignore
        )

    @task
    def market_context_task(self) -> Task:
        return Task(
            config=self.tasks_config["market_context_task"],  # type: ignore
        )

    @task
    def contrarian_check_task(self) -> Task:
        return Task(
            config=self.tasks_config["contrarian_check_task"],  # type: ignore
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,  # type: ignore
            tasks=self.tasks,    # type: ignore
            process=Process.sequential,
            verbose=True,
        )


def run():
    """Entry point for `crewai run` / CrewAI Studio."""
    inputs = {
        "asset": "XAUUSD",
        "market": "ctrader",
        "reason": "H1 lookback move 0.697%, range 2.030%",
        "metrics": {
            "move_pct": 0.697,
            "last_bar_move_pct": 0.109,
            "range_pct": 2.030,
            "period": "H1",
        },
    }
    result = TradingResearchCrew().crew().kickoff(inputs=inputs)
    print(result)


if __name__ == "__main__":
    run()
