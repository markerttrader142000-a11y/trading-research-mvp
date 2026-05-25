"""
src/trading_research/crew.py
─────────────────────────────────────────────────────────────
Formato oficial CrewAI: CrewBase + YAML decorators.

5 crews, cada uma com os seus agentes e tasks definidos em:
  src/trading_research/config/agents.yaml
  src/trading_research/config/tasks.yaml

IMUTÁVEL: execution_enabled: false — research only.
requires_human_approval: true em todos os TradeOpportunity.

Uso:
  from src.trading_research.crew import (
      ResearchSynthesizerCrew,
      SetupValidationCrew,
      TradePlanCrew,
      ExecutionMonitorCrew,
      PostTradeReviewCrew,
  )
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

def _nano_llm():
    """GPT-4.1-nano for fast specialist agents. Falls back to Mistral if no OpenAI key."""
    try:
        from agents.llm_factory import make_llm
        return make_llm(provider="nano")
    except Exception:
        return None

def _mistral_llm():
    """Mistral small for synthesis agents."""
    try:
        from agents.llm_factory import make_llm
        return make_llm(provider="mistral")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Crew 1 — Research Synthesizer
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class ResearchSynthesizerCrew:
    """
    Recebe: List[MarketCandidate] (um por vez via flow)
    Entrega: ResearchItem com macro context, catalysts, risks e sources.

    Agentes: Macro Research Analyst + Market Context Analyst + Contrarian Checker
    """

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    # ── Tier 2: Mistral small — synthesis agents ──────────────
    @agent
    def macro_research_analyst(self) -> Agent:
        return Agent(config=self.agents_config["macro_research_analyst"],  # type: ignore[index]
                     llm=_mistral_llm(), verbose=False, allow_delegation=False)

    @agent
    def market_context_analyst(self) -> Agent:
        return Agent(config=self.agents_config["market_context_analyst"],  # type: ignore[index]
                     llm=_mistral_llm(), verbose=False, allow_delegation=False)

    @agent
    def contrarian_checker(self) -> Agent:
        return Agent(config=self.agents_config["contrarian_checker"],  # type: ignore[index]
                     llm=_mistral_llm(), verbose=False, allow_delegation=False)

    # ── Tier 3: GPT-4.1-nano — specialist agents ─────────────
    @agent
    def sentiment_scorer(self) -> Agent:
        return Agent(config=self.agents_config["sentiment_scorer"],  # type: ignore[index]
                     llm=_nano_llm(), verbose=False, allow_delegation=False)

    @agent
    def news_impact_assessor(self) -> Agent:
        return Agent(config=self.agents_config["news_impact_assessor"],  # type: ignore[index]
                     llm=_nano_llm(), verbose=False, allow_delegation=False)

    @agent
    def technical_validator(self) -> Agent:
        return Agent(config=self.agents_config["technical_validator"],  # type: ignore[index]
                     llm=_nano_llm(), verbose=False, allow_delegation=False)

    # ── Tasks ─────────────────────────────────────────────────
    @task
    def research_macro_task(self) -> Task:
        return Task(config=self.tasks_config["research_macro_task"])  # type: ignore[index]

    @task
    def research_context_task(self) -> Task:
        return Task(config=self.tasks_config["research_context_task"])  # type: ignore[index]

    @task
    def research_contrarian_task(self) -> Task:
        return Task(config=self.tasks_config["research_contrarian_task"])  # type: ignore[index]

    @task
    def sentiment_scoring_task(self) -> Task:
        return Task(config=self.tasks_config["sentiment_scoring_task"])  # type: ignore[index]

    @task
    def news_impact_task(self) -> Task:
        return Task(config=self.tasks_config["news_impact_task"])  # type: ignore[index]

    @task
    def technical_validation_task(self) -> Task:
        return Task(config=self.tasks_config["technical_validation_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Crew 2 — Setup Validation
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class SetupValidationCrew:
    """
    Recebe: TradeOpportunity (stub) + ResearchItem
    Entrega: dict com validated, probability_score, risk_notes, rejection_reason

    Agentes: Setup Validator + Probability Scorer + Risk Annotation Agent
    """

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    @agent
    def setup_validator(self) -> Agent:
        return Agent(config=self.agents_config["setup_validator"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def probability_scorer(self) -> Agent:
        return Agent(config=self.agents_config["probability_scorer"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def risk_annotation_agent(self) -> Agent:
        return Agent(config=self.agents_config["risk_annotation_agent"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @task
    def validation_task(self) -> Task:
        return Task(config=self.tasks_config["validation_task"])  # type: ignore[index]

    @task
    def scoring_task(self) -> Task:
        return Task(config=self.tasks_config["scoring_task"])  # type: ignore[index]

    @task
    def risk_annotation_task(self) -> Task:
        return Task(config=self.tasks_config["risk_annotation_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Crew 3 — Trade Plan
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class TradePlanCrew:
    """
    Recebe: ResearchItem + validation dict
    Entrega: TradeOpportunity com plano completo (entry, SL, TP, thesis…)

    Agentes: Trade Planner + Position Sizing Assistant + Execution Formatter
    """

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    @agent
    def trade_planner(self) -> Agent:
        return Agent(config=self.agents_config["trade_planner"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def position_sizing_assistant(self) -> Agent:
        return Agent(config=self.agents_config["position_sizing_assistant"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def execution_instruction_formatter(self) -> Agent:
        return Agent(config=self.agents_config["execution_instruction_formatter"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @task
    def trade_plan_task(self) -> Task:
        return Task(config=self.tasks_config["trade_plan_task"])  # type: ignore[index]

    @task
    def sizing_task(self) -> Task:
        return Task(config=self.tasks_config["sizing_task"])  # type: ignore[index]

    @task
    def formatting_task(self) -> Task:
        return Task(config=self.tasks_config["formatting_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Crew 4 — Execution Monitor
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class ExecutionMonitorCrew:
    """
    Recebe: List[Dict] open_positions (injectado manualmente)
    Entrega: List[Dict] monitoring_actions

    No-op quando open_positions está vazio (execution_enabled: false).
    Agentes: Trade Monitor + Exception Handler
    """

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    @agent
    def trade_monitor(self) -> Agent:
        return Agent(config=self.agents_config["trade_monitor"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def exception_handler(self) -> Agent:
        return Agent(config=self.agents_config["exception_handler"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @task
    def monitoring_task(self) -> Task:
        return Task(config=self.tasks_config["monitoring_task"])  # type: ignore[index]

    @task
    def exception_task(self) -> Task:
        return Task(config=self.tasks_config["exception_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Crew 5 — Post-Trade Review
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class PostTradeReviewCrew:
    """
    Recebe: Dict closed_trade (injectado manualmente após fecho)
    Entrega: Dict post_trade_journal com lessons + patterns

    No-op quando closed_trade is None.
    Agentes: Journal Writer + Pattern Miner
    """

    agents_config = "config/agents.yaml"
    tasks_config  = "config/tasks.yaml"

    @agent
    def journal_writer(self) -> Agent:
        return Agent(config=self.agents_config["journal_writer"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @agent
    def pattern_miner(self) -> Agent:
        return Agent(config=self.agents_config["pattern_miner"],  # type: ignore[index]
                     verbose=False, allow_delegation=False)

    @task
    def journal_task(self) -> Task:
        return Task(config=self.tasks_config["journal_task"])  # type: ignore[index]

    @task
    def pattern_task(self) -> Task:
        return Task(config=self.tasks_config["pattern_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
