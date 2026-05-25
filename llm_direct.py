"""
LLM Direct — Mistral via LiteLLM + Perplexity real-time search
---------------------------------------------------------------
Pipeline de research em dois passos:
  1. Perplexity (se PERPLEXITY_API_KEY disponível) — busca notícias reais,
     catalisadores e eventos macro em tempo real.
  2. Mistral — sintetiza os dados do Perplexity + métricas do scanner em
     ResearchItem / TradeOpportunity estruturado.

Se o Perplexity não estiver configurado, o Mistral usa apenas os dados
do scanner cTrader (comportamento original).

Funções públicas (mesma assinatura das crews):
  run_research_direct(candidates, config) -> List[ResearchItem]
  run_trade_plan_direct(research, validation, config) -> Optional[TradeOpportunity]
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from schemas import MarketCandidate, ResearchItem, TradeOpportunity


# ---------------------------------------------------------------------------
# Perplexity enrichment (optional — graceful no-op if key not set)
# ---------------------------------------------------------------------------

def _fetch_perplexity_context(candidate: MarketCandidate) -> dict:
    """
    Fetches real-time news context from Perplexity for a candidate.
    Returns a dict with keys: summary, catalysts, risks, macro_events, sources.
    Returns empty dict if Perplexity is unavailable or the call fails.
    """
    try:
        from perplexity_search import search_market_news, is_available
        if not is_available():
            return {}
        result = search_market_news(candidate.asset, market=candidate.market)
        if not result.success:
            return {}
        return {
            "perplexity_summary": result.summary,
            "perplexity_catalysts": result.catalysts,
            "perplexity_risks": result.risks,
            "perplexity_macro_events": result.macro_events,
            "perplexity_sources": result.sources,
        }
    except Exception as exc:
        import sys
        print(f"[llm_direct] Perplexity enrichment skipped: {exc}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# LiteLLM caller
# ---------------------------------------------------------------------------

def _call_mistral(prompt: str, config: dict) -> str:
    """
    Calls Mistral via LiteLLM. Returns the response text.
    Falls back to empty string on error.
    """
    try:
        import litellm  # noqa: PLC0415

        api_key = os.environ.get("MISTRAL_API_KEY", "")
        if not api_key:
            return ""

        model = os.environ.get("CREWAI_LLM_MODEL", "mistral/mistral-small-latest")
        if not model.startswith("mistral/"):
            model = f"mistral/{model}"

        response = litellm.completion(
            model=model,
            api_key=api_key,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional trading research analyst. "
                        "Always respond with valid JSON only — no prose, no markdown fences. "
                        "Your JSON must be parseable by Python json.loads()."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        return str(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[llm_direct] WARNING: Mistral call failed: {exc}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    """Extracts the first valid JSON object from text."""
    # Strip markdown fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _to_list(value, default=None) -> list:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value.strip():
        return [value]
    return default or []


# ---------------------------------------------------------------------------
# Research Synthesizer (Crew 1 replacement)
# ---------------------------------------------------------------------------

def run_research_direct(
    candidates: List[MarketCandidate],
    config: dict,
) -> List[ResearchItem]:
    """
    Calls Mistral directly for each candidate and returns ResearchItems.
    Falls back to mock research if the API call fails.
    """
    items: List[ResearchItem] = []

    for candidate in candidates:
        metrics = candidate.metrics or {}
        metrics_str = json.dumps(metrics) if metrics else "none"

        # Step 1 — Perplexity: fetch real-time news context (optional)
        pctx = _fetch_perplexity_context(candidate)
        has_perplexity = bool(pctx)

        # Build a human-readable metrics note for the prompt
        metrics_note = ""
        if metrics.get("move_pct") is not None:
            metrics_note = (
                f"\nPrice-action context (use these numbers in your summary):\n"
                f"  Lookback move: {metrics.get('move_pct', 0):.3f}%\n"
                f"  Last-bar move: {metrics.get('last_bar_move_pct', 0):.3f}%\n"
                f"  Lookback range: {metrics.get('range_pct', 0):.3f}%\n"
                f"  Period: {metrics.get('period', 'unknown')}"
            )

        # Step 2 — Build Perplexity context block for the Mistral prompt
        perplexity_block = ""
        if has_perplexity:
            perplexity_block = (
                f"\nReal-time news context from Perplexity (use this in your analysis):\n"
                f"  News summary: {pctx.get('perplexity_summary', '')[:300]}\n"
                f"  Live catalysts: {pctx.get('perplexity_catalysts', [])}\n"
                f"  Live risks: {pctx.get('perplexity_risks', [])}\n"
                f"  Macro events: {pctx.get('perplexity_macro_events', [])}\n"
                f"  Sources: {pctx.get('perplexity_sources', [])}"
            )

        # Step 3 — Mistral: synthesise everything into structured ResearchItem
        prompt = (
            f"Research this trading candidate and return ONLY a JSON object.\n\n"
            f"Asset: {candidate.asset}\n"
            f"Market: {candidate.market}\n"
            f"Reason selected: {candidate.reason}\n"
            f"Raw metrics: {metrics_str}"
            f"{metrics_note}"
            f"{perplexity_block}\n\n"
            "Required JSON keys:\n"
            '  "macro_summary": string — 2-3 sentence research summary that integrates '
            'the real-time news context (if provided) AND references the specific '
            'price-action metrics above (move %, range) when available\n'
            '  "bullish_factors": list of 2-3 strings\n'
            '  "bearish_factors": list of 2-3 strings\n'
            '  "catalysts": list of 1-2 strings (prefer real news catalysts if available)\n'
            '  "macro_events": list of strings (upcoming events that could impact price)\n'
            '  "news_risks": list of 1-2 strings\n'
            '  "sources": list of strings (data sources used, include Perplexity sources)\n'
            '  "source_quality_score": float between 0.0 and 1.0 '
            '(use 0.9 if real news was available, 0.7 if price-action only)\n\n'
            "Return ONLY the JSON object. No explanation, no markdown."
        )

        raw = _call_mistral(prompt, config)
        data = _parse_json(raw) if raw else {}

        if data:
            # Merge Perplexity sources with Mistral sources
            mistral_sources = _to_list(data.get("sources"), ["Mistral AI research"])
            perplexity_sources = pctx.get("perplexity_sources", []) if has_perplexity else []
            all_sources = list(dict.fromkeys(mistral_sources + perplexity_sources))  # deduplicate

            # Use higher quality score when real news was available
            base_quality = float(data.get("source_quality_score", 0.75))
            quality = max(base_quality, 0.88) if has_perplexity else base_quality

            item = ResearchItem(
                asset=candidate.asset,
                market=candidate.market,
                summary=str(data.get("macro_summary", f"{candidate.asset} — Mistral research.")),
                bullish_factors=_to_list(data.get("bullish_factors"), ["LLM flagged as candidate."]),
                bearish_factors=_to_list(data.get("bearish_factors"), ["Review crew output."]),
                catalysts=_to_list(data.get("catalysts"), [candidate.reason]),
                macro_events=_to_list(data.get("macro_events"), pctx.get("perplexity_macro_events", [])),
                news_risks=_to_list(data.get("news_risks"), []),
                sources=all_sources[:6],
                source_quality_score=round(quality, 3),
            )
        else:
            # Graceful fallback: use Perplexity data directly if Mistral failed
            if has_perplexity:
                item = _perplexity_fallback_item(candidate, pctx)
            else:
                item = _mock_research_item(candidate)

        items.append(item)

    return items


def _perplexity_fallback_item(candidate: MarketCandidate, pctx: dict) -> ResearchItem:
    """Builds a ResearchItem from Perplexity data when Mistral fails."""
    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=pctx.get("perplexity_summary", f"{candidate.asset} — Perplexity research."),
        bullish_factors=pctx.get("perplexity_catalysts", ["Perplexity flagged as candidate."])[:3],
        bearish_factors=pctx.get("perplexity_risks", ["No Mistral synthesis available."])[:3],
        catalysts=pctx.get("perplexity_catalysts", [candidate.reason])[:2],
        macro_events=pctx.get("perplexity_macro_events", []),
        news_risks=pctx.get("perplexity_risks", [])[:2],
        sources=pctx.get("perplexity_sources", ["Perplexity AI"]),
        source_quality_score=0.82,
    )


def _mock_research_item(candidate: MarketCandidate) -> ResearchItem:
    return ResearchItem(
        asset=candidate.asset,
        market=candidate.market,
        summary=(
            f"{candidate.asset} selected by scanner. "
            "Mistral key not set or call failed — using price-action placeholder."
        ),
        bullish_factors=["Scanner detected qualifying movement/range."],
        bearish_factors=["No external research context available."],
        catalysts=[candidate.reason],
        macro_events=[],
        news_risks=["News context not connected."],
        sources=[candidate.source_hint or "scanner"],
        source_quality_score=0.60,
    )


# ---------------------------------------------------------------------------
# Trade Plan (Crew 3 replacement)
# ---------------------------------------------------------------------------

def run_trade_plan_direct(
    research: ResearchItem,
    validation: dict,
    config: dict,
) -> Optional[TradeOpportunity]:
    """
    Calls Mistral directly to build a trade plan.
    Returns None if validation failed.
    """
    if not validation.get("validated", False):
        return None

    prompt = (
        f"Build a trade plan for this validated setup and return ONLY a JSON object.\n\n"
        f"Asset: {research.asset}\n"
        f"Market: {research.market}\n"
        f"Research summary: {research.summary}\n"
        f"Bullish factors: {research.bullish_factors}\n"
        f"Bearish factors: {research.bearish_factors}\n"
        f"Catalysts: {research.catalysts}\n"
        f"Validation probability: {validation.get('probability_score', 0.65)}\n"
        f"Risk notes: {validation.get('risk_notes', [])}\n\n"
        "Required JSON keys:\n"
        '  "direction": "long" or "short" or "neutral"\n'
        '  "setup_type": string (e.g. "momentum_breakout", "mean_reversion")\n'
        '  "thesis": string — 2-3 sentence trade thesis\n'
        '  "counter_thesis": string — main risk to the thesis\n'
        '  "entry_logic": string — specific entry condition\n'
        '  "stop_logic": string — stop loss condition\n'
        '  "target_logic": string — profit target logic (min R:R 1.5)\n'
        '  "invalidation_conditions": list of 2-3 strings\n'
        '  "confidence_initial": float between 0.0 and 1.0\n\n'
        "Return ONLY the JSON object. No explanation, no markdown."
    )

    raw = _call_mistral(prompt, config)
    data = _parse_json(raw) if raw else {}

    direction = str(data.get("direction", _infer_direction(research))).lower()
    if direction not in ("long", "short", "neutral"):
        direction = _infer_direction(research)

    confidence = float(data.get("confidence_initial",
        validation.get("probability_score", 0.65)))

    # Recover cTrader metrics from the catalyst text so the ranking engine
    # can use real move_pct / range_pct values instead of empty dict
    catalyst_text = research.catalysts[0] if research.catalysts else ""
    metrics = _parse_ctrader_metrics(catalyst_text) if research.market == "ctrader" else {}

    return TradeOpportunity(
        asset=research.asset,
        market=research.market,
        direction=direction,
        setup_type=str(data.get("setup_type", "mistral_direct_plan")),
        thesis=str(data.get("thesis", research.summary[:300])),
        counter_thesis=str(data.get("counter_thesis",
            research.bearish_factors[0] if research.bearish_factors else "Unknown risk.")),
        catalyst=catalyst_text or "Mistral-generated.",
        timeframe=config.get("timeframe", "intraday_or_swing"),
        confidence_initial=round(min(1.0, max(0.0, confidence)), 3),
        entry_logic=str(data.get("entry_logic",
            "Wait for chart confirmation before entry.")),
        stop_logic=str(data.get("stop_logic",
            "Invalidate if price reverses through key structure.")),
        target_logic=str(data.get("target_logic",
            "Target only if nearby structure allows ≥ 1.5R.")),
        invalidation_conditions=_to_list(
            data.get("invalidation_conditions"),
            research.news_risks or ["Review output for invalidation conditions."],
        ),
        requires_chart_validation=True,
        requires_human_approval=True,
        metrics=metrics,
    )


def _infer_direction(research: ResearchItem) -> str:
    catalyst = research.catalysts[0].lower() if research.catalysts else ""
    if any(w in catalyst for w in ("downside", "short", "bearish", "sell")):
        return "short"
    return "long"


def _parse_ctrader_metrics(catalyst: str) -> dict:
    """Recovers cTrader numeric metrics from the catalyst text string."""
    import re

    def find(pattern: str) -> float:
        match = re.search(pattern, catalyst)
        return float(match.group(1)) if match else 0.0

    period_match = re.search(r"period=([A-Z0-9]+)", catalyst)
    return {
        "move_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback move"),
        "last_bar_move_pct": find(r"([-+]?\d+(?:\.\d+)?)% last-bar move"),
        "range_pct": find(r"([-+]?\d+(?:\.\d+)?)% lookback range"),
        "period": period_match.group(1) if period_match else None,
    }
