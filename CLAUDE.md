# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Autonomous trading **research** pipeline — no order execution, no real money. Output is a ranked JSON watchlist for human review. The system scans cTrader market data, calls Mistral AI for research and trade plans, filters by risk, ranks by score, and prints the final report.

**Immutable constraint**: `execution_enabled: false` in `config.yaml` and `requires_human_approval: true` on every `TradeOpportunity`. Never remove these. Never wire up order submission.

## Environment Setup

**Python 3.11 required** (crewai >= 0.80 needs 3.10+, project uses 3.11):

```bash
cd ~/Desktop/trading_research_mvp_ctrader_v7
source .venv/bin/activate          # always activate before running anything
python3 main.py --runner simple    # primary run command
python3 main.py --runner langgraph # LangGraph runner (requires langgraph installed)
python3 main.py --no-save          # skip SQLite write
```

**Diagnostic scripts** (run from project root with venv active):

```bash
python3 check_ctrader_config.py      # verify cTrader env vars are loaded
python3 check_ctrader_accounts.py    # list accounts on current token
python3 check_ctrader_trendbars.py   # pull live H1 trendbars for configured symbols
python3 check_alpaca_config.py       # verify Alpaca credentials
python3 ctrader_auth.py              # OAuth flow — opens browser, saves .ctrader_tokens.json
```

**Required env vars** (in `.env`, loaded by `main.py` via `python-dotenv`):

```
MISTRAL_API_KEY=...              # primary LLM — mistral-small-latest via LiteLLM
CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
CTRADER_REDIRECT_URI=http://localhost:8080/callback
CTRADER_ENV=demo
CREWAI_TRACING_ENABLED=false    # prevents crewai from opening browser trace UI
```

Alpaca credentials are auto-discovered from `.env`, `~/.env`, or `~/trading/alpaca_config.json`.

## Architecture: 3-Layer Pipeline

```
Layer 1 — Data       scanner.py          MarketCandidate[]
Layer 2 — Workflow   graph.py            LangGraph StateGraph (or simple sequential)
Layer 3 — AI         llm_direct.py       Mistral via LiteLLM (primary path)
                     crews/              CrewAI crews (fallback path)
```

**State object**: `TradingResearchState` (Pydantic v2, `schemas.py`) flows through every node:
`raw_candidates → research_items → opportunities → filtered_opportunities → ranked_opportunities → final_report`

### Node execution order (graph.py)

1. `autonomous_scan` — `scanner.py`: calls cTrader Open API (H1 trendbars), Alpaca, or mock. Populates `raw_candidates` with `MarketCandidate` objects including `metrics` dict (`move_pct`, `last_bar_move_pct`, `range_pct`, `period`, `trendbar_count`, `scan_score`).
2. `research_candidates` — calls Mistral directly via `llm_direct.run_research_direct()`. Falls back to CrewAI `research_synthesizer`, then legacy mock. Returns `ResearchItem[]`.
3. `generate_opportunities` — calls `llm_direct.run_trade_plan_direct()` per item. **Critically**: after Mistral returns a plan, the node restores scanner `metrics` from `raw_candidates` if the plan's metrics dict is empty (Mistral doesn't know the raw numbers unless they're in the catalyst text). Falls back to CrewAI crews, then legacy mock. Returns `TradeOpportunity[]`.
4. `risk_quality_filter` — `risk_filter.py`: deterministic, no LLM. Rejects if `confidence_initial < 0.55`, no catalyst, no invalidation conditions, or `direction == "neutral"`.
5. `rank_opportunities` — `ranking.py`: scores each opportunity using `confidence_score + source_score + catalyst_score + clarity_score + move_score + range_score - penalties`. Penalty for last-bar contradicting overall direction (`last_bar_penalty`), chart validation flag, and human approval flag.
6. `build_report` — `report.py`: assembles `TradingResearchState.final_report` dict, printed as JSON by `main.py`.

### Priority fallback pattern (graph.py nodes 2 & 3)

Every AI node follows this pattern:
```python
if os.environ.get("MISTRAL_API_KEY"):
    # 1. llm_direct — fastest, no crewai dependency
if crewai_available:
    # 2. CrewAI crews — full multi-agent pipeline
# 3. legacy mock in research.py / opportunity.py
```

## Key Files

| File | Role |
|------|------|
| `schemas.py` | All Pydantic v2 models. Source of truth for data shapes. |
| `graph.py` | Pipeline orchestration. All node wiring + fallback logic. `_direct_validate()` and `_stub_opportunity()` helpers live here. |
| `llm_direct.py` | Mistral integration (no crewai). `run_research_direct()`, `run_trade_plan_direct()`, `_parse_ctrader_metrics()`, `_parse_json()`. |
| `scanner.py` | Market data. cTrader Open API trendbars (primary), Alpaca (fallback), mock. **All provider imports are lazy** (inside functions) to avoid import errors when credentials are missing. |
| `ranking.py` | Deterministic scoring. Adjust weights here for tuning. |
| `risk_filter.py` | Deterministic rejection. Adjust thresholds via `config.yaml risk:` section. |
| `agents/llm_factory.py` | `make_llm(provider)` — returns a CrewAI-compatible LLM object. Supports mistral, anthropic, openai, perplexity, gemini, grok, deepseek. Returns `None` → mock path. |
| `crews/` | 5 CrewAI crews. Crew 1 (research_synthesizer), Crew 2 (setup_validation), Crew 3 (trade_plan) are wired. Crews 4+5 (execution_monitor, post_trade_review) are scaffolded but not connected. |
| `config.yaml` | All tunable parameters. `data.provider: ctrader` to force cTrader. `models.mode: mistral` sets LLM. |
| `storage.py` | SQLite persistence to `data/runs.db`. Wrapped in try/except — failures are non-fatal. |
| `market_data.py` | Alpaca REST client. `get_data_provider_status()` import in `report.py` is lazy. |
| `ctrader_client.py` | cTrader Open API async client (twisted). Fetches accounts + trendbars. |

## Current State & Pending Work

**Working** (as of last session):
- Full pipeline runs cleanly: `errors: []`
- Mistral generates research summaries that reference real cTrader metrics (move_pct, range_pct)
- Trade plans cite exact percentage moves from the scanner
- Ranking `why` field shows dynamic text (`"movimento forte (0.697%); range amplo (2.030%)"`)
- USDJPY correctly detected as short from negative `move_pct`
- 4 cTrader symbols: EURUSD, GBPUSD, USDJPY, XAUUSD (H1, 50 bars)
- **CrewAI Crew 1 (Research Synthesizer) now runs with real Mistral** — all 3 agents produce real LLM output

**CrewAI + Mistral fix (agents/llm_factory.py)**:
`crewai.LLM.__new__` strips the `mistral/` prefix before passing to litellm, so litellm gets `mistral-small-latest` without provider context and returns `None`. Fix: `_make_mistral()` now returns a `MistralLiteLLMWrapper` (subclass of `crewai.llms.base_llm.BaseLLM`) that calls `litellm.completion()` directly with the full `mistral/mistral-small-latest` model string and strips `cache_breakpoint` fields that crewai injects but Mistral rejects (422 error).

**Pending**:
- Dashboard/UI for ranked opportunities.

**Crews 4+5 wired (graph.py)**:
Both nodes are now part of the pipeline, running after `build_report`:
- `monitor_executions` → Crew 4 (Execution Monitor): no-op when `state.open_positions` is empty; real crew runs when a human injects position data externally
- `post_trade_review` → Crew 5 (Post-Trade Review): no-op when `state.closed_trade` is None; real crew runs when a human injects a closed trade dict

`TradingResearchState` has two new optional field groups (safe defaults, backward-compatible):
- `open_positions: List[Dict]` + `monitoring_actions: List[Dict]` (Crew 4)
- `closed_trade: Optional[Dict]` + `post_trade_journal: Dict` (Crew 5)

`report.py` exposes both under `"monitoring"` and `"post_trade_journal"` keys in the final JSON.

## Important Patterns

**Scanner metrics preservation**: `generate_opportunities()` in `graph.py` builds a `scanner_metrics` dict from `state.raw_candidates` before calling Mistral. After each plan is returned, if `not any(plan.metrics.values())`, it restores metrics from `scanner_metrics.get(item.asset, {})`. This is essential — without it, ranking has no real move/range data.

**Lazy imports in scanner.py**: `from ctrader_open_api import ...` and Alpaca imports are inside the scan functions. Do not move them to top-level — they fail when the packages aren't installed or credentials are missing.

**report.py lazy import**: `get_data_provider_status()` is wrapped in a `_data_provider_status()` function. Same reason.

**JSON parsing in llm_direct.py**: `_parse_json()` strips markdown fences, then finds the first `{...}` block. Mistral occasionally wraps output in triple backticks despite instructions — the parser handles both cases.

**Pydantic serializer warnings** from litellm are cosmetic and expected — litellm's internal `Message` schema differs slightly from what pydantic expects. Safe to ignore.
