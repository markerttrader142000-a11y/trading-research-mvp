from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Load .env before anything else so API keys are available to all modules
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path, override=False)
    except ImportError:
        pass  # dotenv optional — keys can be set in shell environment

_load_env()

from config import load_config
from graph import run_langgraph_workflow, run_simple_workflow
from schemas import TradingResearchState
from storage import save_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous trading research MVP. No execution, research/report only."
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument(
        "--runner",
        choices=["simple", "langgraph"],
        default="simple",
        help="Use simple fallback runner or LangGraph runner.",
    )
    parser.add_argument("--no-save", action="store_true", help="Do not save run to SQLite.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    state = TradingResearchState(
        markets=config.get("markets", ["forex", "indices", "commodities"]),
        timeframe=config.get("timeframe", "intraday_or_swing"),
        max_candidates=int(config.get("max_candidates", 10)),
        max_final_opportunities=int(config.get("max_final_opportunities", 5)),
        config=config,
    )

    if args.runner == "langgraph":
        state = run_langgraph_workflow(state)
    else:
        state = run_simple_workflow(state)

    if not args.no_save:
        save_run(state)

    print(json.dumps(state.final_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

