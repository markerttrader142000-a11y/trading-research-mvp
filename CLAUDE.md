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
OPENAI_API_KEY=...               # GPT-4.1-nano fallback + specialist agents
PERPLEXITY_API_KEY=...           # real-time news search (Perplexity sonar)
SLACK_WEBHOOK_URL=...            # Human-in-the-loop Slack notifications
CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
CTRADER_REDIRECT_URI=http://localhost:8080/callback
CTRADER_ENV=demo
CREWAI_TRACING_ENABLED=false    # prevents crewai from opening browser trace UI
```

Alpaca credentials are auto-discovered from `.env`, `~/.env`, or `~/trading/alpaca_config.json`.

## Architecture: 4-Layer Pipeline

```
Layer 1 — Data         scanner.py           MarketCandidate[]
Layer 2 — News         perplexity_search.py real-time catalysts (optional)
Layer 3 — Workflow     graph.py             LangGraph StateGraph (or simple sequential)
Layer 4 — AI           llm_direct.py        Mistral primary → GPT-4.1-nano fallback
                       crews/               CrewAI crews (6 agents in Crew 1)
Layer 5 — Notifications slack_notify.py     Slack HiTL per opportunity
           Observability observability.py   Structured JSONL logs in data/logs/
```

**LLM cost hierarchy**:
- Perplexity `sonar` → news fetch (cheapest, real-time web)
- Mistral `small` → JSON synthesis (primary, free tier)
- GPT-4.1-nano → automatic fallback when Mistral 503/429 + specialist agents
- GPT-4.1-mini → complex trade plans (optional upgrade)

**State object**: `TradingResearchState` (Pydantic v2, `schemas.py`) flows through every node:
`raw_candidates → research_items → opportunities → filtered_opportunities → ranked_opportunities → final_report`

### Node execution order (graph.py)

1. `autonomous_scan` — `scanner.py`: calls cTrader Open API (H1 trendbars), Alpaca, or mock. Populates `raw_candidates` with `MarketCandidate` objects including `metrics` dict (`move_pct`, `last_bar_move_pct`, `range_pct`, `period`, `trendbar_count`, `scan_score`).
2. `research_candidates` — `perplexity_search.py` fetches live news first, then `llm_direct.run_research_direct()` synthesises with Mistral (fallback: GPT-4.1-nano → CrewAI crew → mock).
3. `generate_opportunities` — calls `llm_direct.run_trade_plan_direct()` per item. After plan returned, restores scanner `metrics` from `raw_candidates` if plan's metrics dict is empty. Fallback chain: Mistral → GPT-4.1-nano → CrewAI → mock.
4. `risk_quality_filter` — `risk_filter.py`: deterministic, no LLM. Rejects if `confidence_initial < 0.55`, no catalyst, no invalidation conditions, or `direction == "neutral"`.
5. `rank_opportunities` — `ranking.py`: scores using `confidence_score + source_score + catalyst_score + clarity_score + move_score + range_score - penalties`.
6. `build_report` — `report.py`: assembles `TradingResearchState.final_report` dict.
7. `monitor_executions` — Crew 4: no-op when `state.open_positions` is empty.
8. `post_trade_review` — Crew 5: no-op when `state.closed_trade` is None.
9. `notify_and_log` — sends Slack messages for top 3 opportunities + run summary, flushes tracer to `data/logs/`.

### LLM fallback pattern (_call_llm in llm_direct.py)

```python
def _call_llm(prompt, config):
    result = _call_mistral(prompt, config)  # Mistral small
    if result:
        return result
    return _call_nano(prompt)               # GPT-4.1-nano automatic fallback
```

## Key Files

| File | Role |
|------|------|
| `schemas.py` | All Pydantic v2 models. Source of truth for data shapes. |
| `graph.py` | Pipeline orchestration. 9 nodes including `notify_and_log`. Tracer initialised at start of `run_simple_workflow`. |
| `llm_direct.py` | Mistral + GPT-4.1-nano. `_call_llm()` tries Mistral first, falls back to nano automatically. `run_research_direct()` calls Perplexity first, then synthesises with `_call_llm()`. |
| `perplexity_search.py` | Perplexity sonar client. `search_market_news(asset, market)` → `PerplexityResult`. Graceful no-op if `PERPLEXITY_API_KEY` not set. |
| `slack_notify.py` | Slack Incoming Webhook. `notify_opportunities(ranked, run_id)` + `notify_run_summary(state_dict, run_id)`. Block Kit rich messages. |
| `observability.py` | Structured JSONL tracing. `Tracer` class with `span()` context manager. Writes to `data/logs/run_<date>_<trace_id[:8]>.jsonl` + `data/logs/latest.jsonl`. |
| `scanner.py` | Market data. cTrader Open API trendbars (primary), Alpaca (fallback), mock. **All provider imports are lazy**. |
| `ranking.py` | Deterministic scoring. Adjust weights here for tuning. |
| `risk_filter.py` | Deterministic rejection. Adjust thresholds via `config.yaml risk:` section. |
| `agents/llm_factory.py` | `make_llm(provider)`. Providers: mistral, nano (GPT-4.1-nano), mini (GPT-4.1-mini), anthropic, openai, perplexity, gemini, grok, deepseek. |
| `src/trading_research_mvp/crew.py` | 5 CrewBase crews. Crew 1 has 6 agents: 3 Mistral (synthesis) + 3 GPT-4.1-nano (sentiment_scorer, news_impact_assessor, technical_validator). |
| `src/trading_research_mvp/config/agents.yaml` | 14 agent definitions including 3 new specialist agents. |
| `src/trading_research_mvp/config/tasks.yaml` | 17 task definitions including sentiment_scoring_task, news_impact_task, technical_validation_task. |
| `config.yaml` | All tunable parameters. `data.provider: ctrader`. Symbols: EURUSD, GBPUSD, USDJPY, XAUUSD. |
| `storage.py` | SQLite persistence to `data/runs.db`. Non-fatal. |
| `ctrader_client.py` | cTrader Open API async client (twisted). |

## Current State (2026-05-25 — end of session)

**Fully working**:
- Pipeline runs cleanly: `errors: []`
- Perplexity fetches real-time news per asset before Mistral synthesis
- Mistral generates research with real cTrader metrics + live news context
- GPT-4.1-nano activates automatically when Mistral returns 503/429
- Slack receives rich Block Kit messages for top 3 opportunities + run summary
- Observability logs written to `data/logs/` as JSONL with trace IDs
- CrewAI deployed: `e69d8f51-8c17-4a51-9d1b-412c15ab2920` (Crew is Online)
- GitHub: `https://github.com/markerttrader142000-a11y/trading-research-mvp`

**Pending (next session)**:
- Expand cTrader symbols beyond 4 (EURUSD, GBPUSD, USDJPY, XAUUSD)
- Scheduling — run automatically every N hours (cron or CrewAI scheduler)
- Dashboard update — show logs and trace IDs in real time
- Connect GPT-4.1-nano specialist agents output back into ranking score

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
