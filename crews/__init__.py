"""
CrewAI Crews
------------
Five operational crews that implement the Analysis Workflows Layer (Layer 3).

Each crew receives structured input from LangGraph and returns structured output.
The LLM provider is controlled by agents/llm_factory.py and config.yaml.

Crew 1 — Research Synthesizer   : replaces research.py mock
Crew 2 — Setup Validation       : validates trade candidates
Crew 3 — Trade Plan             : replaces opportunity.py mock
Crew 4 — Execution Monitor      : monitors open trades
Crew 5 — Post-Trade Review      : journaling and pattern mining
"""
