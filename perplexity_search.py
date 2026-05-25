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
        f"Summarise the current market situation for {asset} ({market_context}). "
        f"What are the main macro themes, recent central bank stance, and key risks "
        f"affecting this instrument right now? "
        f"Include any relevant economic data released recently or upcoming events. "
        f"Keep it concise — 3 to 5 sentences is enough."
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
            "model": "sonar" if model == "sonar" else "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise financial market analyst. "
                        "Summarise the current macro context and key drivers for the "
                        "requested asset. Use your knowledge and any available search "
                        "results. If specific news is unavailable, provide the general "
                        "macro backdrop and key risks. Always respond in plain prose."
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
    Strategy: clean the text first, then split into sentences and categorise.
    """
    # Clean markdown FIRST before any extraction
    clean = re.sub(r"\[\d+\]", "", raw_text)           # remove [1] [2] citations
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)  # remove **bold**
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)       # remove *italic*
    clean = re.sub(r"#+\s+", "", clean)                 # remove ## headers
    clean = re.sub(r"^[-•]\s+", "", clean, flags=re.MULTILINE)  # remove bullets
    clean = re.sub(r"\s{2,}", " ", clean).strip()       # collapse whitespace

    # Skip if Perplexity refused to answer
    refusal_signals = ["i don't have enough", "i cannot provide", "no reliable"]
    if any(s in clean.lower()[:200] for s in refusal_signals):
        # Try to use whatever it did say after the refusal
        parts = clean.split(".")
        useful = [p.strip() for p in parts if len(p.strip()) > 40
                  and not any(s in p.lower() for s in refusal_signals)]
        if not useful:
            return PerplexityResult(asset=asset, success=False)
        clean = ". ".join(useful)

    # Split into complete sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean)
                 if len(s.strip()) > 30]

    # Summary = first 2 meaningful sentences
    summary = " ".join(sentences[:2])[:500]

    # Catalysts = sentences with bullish/upside keywords
    catalyst_kws = ["support", "bullish", "rally", "upside", "rate cut",
                    "easing", "strong", "positive", "catalyst", "boost",
                    "higher", "rise", "gain"]
    catalysts = [s for s in sentences
                 if any(k in s.lower() for k in catalyst_kws)
                 and len(s) > 40][:3]

    # Risks = sentences with bearish/downside keywords
    risk_kws = ["risk", "weak", "downside", "bearish", "pressure", "concern",
                "cut", "decline", "fall", "miss", "uncertainty", "shock",
                "inflation", "recession", "slower"]
    risks = [s for s in sentences
             if any(k in s.lower() for k in risk_kws)
             and len(s) > 40][:3]

    # Macro events = sentences mentioning central banks or data
    macro_kws = ["fed", "ecb", "boj", "boe", "fomc", "central bank",
                 "cpi", "gdp", "nfp", "payroll", "rate decision",
                 "powell", "lagarde", "meeting", "data"]
    macro_events = [s for s in sentences
                    if any(k in s.lower() for k in macro_kws)
                    and len(s) > 40][:3]

    # Fallback: if nothing extracted, use first 3 sentences
    if not catalysts:
        catalysts = sentences[1:3] if len(sentences) > 1 else []
    if not risks:
        risks = sentences[2:4] if len(sentences) > 2 else []

    sources = _extract_sources(raw_text) or ["Perplexity AI real-time search"]

    return PerplexityResult(
        asset=asset,
        summary=summary,
        catalysts=catalysts,
        risks=risks,
        macro_events=macro_events,
        sources=sources[:5],
        raw_text=raw_text,
        success=True,
    )


def _extract_items(text: str, keywords: List[str]) -> List[str]:
    """Extracts complete sentences containing any of the keywords."""
    results = []
    # Split on sentence boundaries (period/!/? followed by space+capital)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    for sentence in sentences:
        sentence = sentence.strip()
        # Skip very short or very long fragments
        if len(sentence) < 25 or len(sentence) > 400:
            continue
        # Skip sentences that are just refusals/meta-commentary
        lower = sentence.lower()
        if any(skip in lower for skip in ["i don't have", "i cannot", "fallback", "if you want"]):
            continue
        if any(kw in lower for kw in keywords):
            # Clean up bullet markers and markdown
            clean = re.sub(r"^[-•*\d.]+\s*", "", sentence)
            clean = re.sub(r"\*+", "", clean).strip()
            if clean and clean not in results:
                results.append(clean[:250])
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
    # Load .env so the script works when run directly
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    asset = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    print(f"Searching Perplexity for {asset}...")
    print(f"API key present: {bool(os.environ.get('PERPLEXITY_API_KEY'))}")
    result = search_market_news(asset, market="forex")
    if result.success:
        print(f"\nSummary: {result.summary}")
        print(f"\nCatalysts: {result.catalysts}")
        print(f"\nRisks: {result.risks}")
        print(f"\nMacro events: {result.macro_events}")
        print(f"\nSources: {result.sources}")
    else:
        print("Call failed — check key and model name.")
