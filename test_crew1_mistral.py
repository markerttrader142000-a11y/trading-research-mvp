"""Teste do Crew 1 (Research Synthesizer) com Mistral real."""
import sys, os

# Desactivar tracing CrewAI antes de importar qualquer coisa
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"

sys.path.insert(0, os.path.expanduser("~/Desktop/trading_research_mvp_ctrader_v7"))

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/Desktop/trading_research_mvp_ctrader_v7/.env"))

from schemas import MarketCandidate
from crews.research_synthesizer import run_research_synthesizer

candidates = [
    MarketCandidate(
        asset="XAUUSD",
        market="ctrader",
        reason="H1 lookback move 0.697%, range 2.030%",
        timeframe="H1",
        metrics={
            "move_pct": 0.697,
            "last_bar_move_pct": 0.109,
            "range_pct": 2.030,
            "period": "H1",
            "scan_score": 0.82,
        },
    )
]

config = {"models": {"research": "mistral"}}

print("A correr Crew 1 — Research Synthesizer com Mistral...")
results = run_research_synthesizer(candidates, config)

for item in results:
    print(f"\nAsset: {item.asset}")
    print(f"Summary: {item.summary[:200]}")
    print(f"Bullish: {item.bullish_factors}")
    print(f"Bearish: {item.bearish_factors}")
    print(f"Catalysts: {item.catalysts}")
    print(f"Source quality: {item.source_quality_score}")
    is_mock = "mock" in item.summary.lower() or "replace with" in item.summary.lower()
    print(f"Real LLM output: {'NO (mock)' if is_mock else 'YES'}")

print("\nDone.")
