"""
perplexity_search.py
────────────────────────────────────────────────────────────
Perplexity AI search client for real-time market research.

Used by llm_direct.py (run_research_direct) to fetch live
news, catalysts and macro context BEFORE Mistral synthesises
the final ResearchItem.

The Perplexity API is OpenAI-compatible — we call it directly
via requests (no extra SDK dependency needed).

Models used:
  sonar          → fast, real-time web search (default)
  sonar-pro      → deeper search, higher cost
  sonar-reasoning → chain-of-thought + search

Env var: PERPLEXITY_API_KEY

Usage (internal):
  from perplexity_search import search_market_news
  context = search_market_news("EURUSD", "forex")
  # returns PerplexityResult with .summary, .catalysts, .risks, .sources
"""
from __future__ import annotations

import os
import re
import json
import sys
from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PerplexityResult:
    """Structured output from a Perplexity search."""
    asset: str
    summary: str = ""
    catalysts: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    macro_events: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    raw_text: str = ""
    success: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def search_market_news(
    asset: str,
    market: str = "forex",
    model: str = "sonar",
    max_tokens: int = 512,
) -> PerplexityResult:
    """
    Search Perplexity for real-time news and catalysts for an asset.

    Returns a PerplexityResult. If PERPLEXITY_API_KEY is not set or the
    call fails, returns a result with success=False (caller falls back
    to Mistral-only research).

    Args:
        asset:      Ticker/symbol, e.g. "EURUSD", "XAUUSD", "AAPL"
        market:     Market type hint, e.g. "forex", "crypto", "equity"
        model:      Perplexity model — "sonar" (fast) or "sonar-pro" (deep)
        max_tokens: Max tokens for the response
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return PerplexityResult(asset=asset, success=False)

    query = _build_query(asset, market)
    raw = _call_perplexity(query, api_key, model, max_tokens)

    if not raw:
        return PerplexityResult(asset=asset, success=False)

    return _parse_response(asset, raw)


def is_available() -> bool:
    """Returns True if PERPLEXITY_API_KEY is set."""
    return bool(os.environ.get("PERPLEXITY_API_KEY", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_query(asset: str, market: str) -> str:
    """Builds a focused search query for the asset."""
    today_hint = "today"

    market_context = {
        "forex":  "foreign exchange currency pair",
        "crypto": "cryptocurrency",
        "equity": "stock",
        "ctrader": "forex/CFD instrument",
        "futures": "futures contract",
        "commodity": "commodity",
    }.get(market.lower(), "financial instrument")

    return (
        f"What are the key news, catalysts, and macro drivers for {asset} "
        f"({market_context}) {today_hint}? "
        f"Include: recent central bank statements, economic data releases, "
        f"geopolitical events, and technical levels if relevant. "
        f"Be concise and factual. Focus on actionable trading catalysts."
    )


def _call_perplexity(
    query: str,
    api_key: str,
    model: str,
    max_tokens: int,
) -> str:
    """
    Calls the Perplexity API (OpenAI-compatible endpoint).
    Returns the response text or empty string on failure.
    """
    try:
        import requests  # already in requirements

        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": f"llama-3.1-sonar-small-128k-online" if model == "sonar" else "llama-3.1-sonar-large-128k-online",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional financial market analyst with access to "
                        "real-time news. Provide factual, concise analysis of market "
                        "catalysts and risks. Be specific about events and data."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "return_citations": True,
            "search_recency_filter": "day",
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    except Exception as exc:
        print(f"[perplexity_search] WARNING: API call failed: {exc}", file=sys.stderr)
        return ""


def _parse_response(asset: str, raw_text: str) -> PerplexityResult:
    """
    Parses Perplexity's free-text response into a structured PerplexityResult.
    Uses simple heuristics — no LLM needed for parsing.
    """
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    # Extract summary (first 2-3 sentences of meaningful content)
    summary_lines = []
    for line in lines[:8]:
        if len(line) > 40 and not line.startswith("#"):
            summary_lines.append(line)
        if len(summary_lines) >= 2:
            break
    summary = " ".join(summary_lines)[:500] or raw_text[:300]

    # Extract catalysts (bullet points or sentences with catalyst keywords)
    catalysts = _extract_items(raw_text, keywords=[
        "catalyst", "driver", "boost", "rally", "surge", "rise",
        "bullish", "positive", "support", "upside", "rate hike",
        "strong", "beat", "exceed"
    ])

    # Extract risks (sentences with risk keywords)
    risks = _extract_items(raw_text, keywords=[
        "risk", "concern", "bearish", "sell", "decline", "fall",
        "weak", "miss", "below", "downside", "pressure", "war",
        "inflation", "recession", "uncertainty"
    ])

    # Extract macro events (dates, central bank mentions, data releases)
    macro_events = _extract_macro_events(raw_text)

    # Extract source citations if present (Perplexity includes [1], [2], etc.)
    sources = _extract_sources(raw_text)
    if not sources:
        sources = ["Perplexity AI real-time search"]

    return PerplexityResult(
        asset=asset,
        summary=summary,
        catalysts=catalysts[:3],
        risks=risks[:3],
        macro_events=macro_events[:3],
        sources=sources[:5],
        raw_text=raw_text,
        success=True,
    )


def _extract_items(text: str, keywords: List[str]) -> List[str]:
    """Extracts sentences containing any of the keywords."""
    results = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue
        lower = sentence.lower()
        if any(kw in lower for kw in keywords):
            # Clean up bullet markers
            clean = re.sub(r"^[-•*\d.]+\s*", "", sentence).strip()
            if clean and clean not in results:
                results.append(clean[:200])
    return results


def _extract_macro_events(text: str) -> List[str]:
    """Extracts sentences mentioning central banks, data releases, or scheduled events."""
    macro_keywords = [
        "fed", "ecb", "boj", "boe", "fomc", "central bank",
        "cpi", "ppi", "gdp", "nfp", "payroll", "inflation",
        "interest rate", "rate decision", "meeting", "speech",
        "powell", "lagarde", "ueda", "bailey",
    ]
    return _extract_items(text, macro_keywords)


def _extract_sources(text: str) -> List[str]:
    """Extracts URLs or citation markers from Perplexity response."""
    # Perplexity sometimes includes URLs in brackets
    urls = re.findall(r"https?://[^\s\]>]+", text)
    # Deduplicate and clean
    seen = set()
    clean = []
    for url in urls:
        domain = re.sub(r"https?://(?:www\.)?([^/]+).*", r"\1", url)
        if domain not in seen:
            seen.add(domain)
            clean.append(domain)
    return clean


# ─────────────────────────────────────────────────────────────────────────────
# Quick test (run directly: python3 perplexity_search.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    asset = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    print(f"Searching Perplexity for {asset}...")
    result = search_market_news(asset, market="forex")
    if result.success:
        print(f"\nSummary: {result.summary}")
        print(f"\nCatalysts: {result.catalysts}")
        print(f"\nRisks: {result.risks}")
        print(f"\nMacro events: {result.macro_events}")
        print(f"\nSources: {result.sources}")
    else:
        print("PERPLEXITY_API_KEY not set or call failed.")
