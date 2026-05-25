from __future__ import annotations

# NOTE: ctrader_client and market_data are imported lazily inside each
# provider function so that mock mode works without those packages installed.
from schemas import MarketCandidate, TradingResearchState


def _mock_scan(state: TradingResearchState) -> TradingResearchState:
    mock_candidates = [
        MarketCandidate(
            asset="EUR/USD",
            market="forex",
            reason="High macro sensitivity and potential USD repricing after economic data.",
            catalyst_type="macro",
            timeframe=state.timeframe,
            source_hint="macro calendar and FX news",
        ),
        MarketCandidate(
            asset="Gold",
            market="commodities",
            reason="Safe-haven demand and rate-expectation sensitivity create potential volatility.",
            catalyst_type="rates_safe_haven",
            timeframe=state.timeframe,
            source_hint="commodities news",
        ),
        MarketCandidate(
            asset="NASDAQ 100",
            market="indices",
            reason="Large-cap technology momentum and rates sensitivity may create index setup.",
            catalyst_type="risk_sentiment",
            timeframe=state.timeframe,
            source_hint="index futures and tech sentiment",
        ),
    ]

    allowed_markets = set(state.markets)
    state.raw_candidates = [
        candidate for candidate in mock_candidates if candidate.market in allowed_markets
    ][: state.max_candidates]
    return state


def _alpaca_scan(state: TradingResearchState) -> TradingResearchState:
    from market_data import fetch_alpaca_stock_bars  # lazy import
    data_config = state.config.get("data", {})
    alpaca_config = data_config.get("alpaca", {})
    min_abs_move_pct = float(alpaca_config.get("min_abs_move_pct", 1.0))

    rows = fetch_alpaca_stock_bars(state.config)
    rows = sorted(
        rows,
        key=lambda row: (abs(float(row["day_move_pct"])), abs(float(row["move_pct"])), float(row["volume"])),
        reverse=True,
    )

    candidates = []
    for row in rows:
        if abs(float(row["day_move_pct"])) < min_abs_move_pct and abs(float(row["move_pct"])) < min_abs_move_pct:
            continue

        direction_hint = "upside momentum" if float(row["day_move_pct"]) >= 0 else "downside momentum"
        candidates.append(
            MarketCandidate(
                asset=str(row["symbol"]),
                market="stocks",
                reason=(
                    f"Alpaca data shows {direction_hint}: "
                    f"{row['day_move_pct']}% last-bar move, {row['move_pct']}% lookback move, "
                    f"{row['range_pct']}% lookback range."
                ),
                catalyst_type="price_momentum",
                timeframe=state.timeframe,
                source_hint="Alpaca historical stock bars",
            )
        )

    state.raw_candidates = candidates[: state.max_candidates]
    return state


def _ctrader_scan(state: TradingResearchState) -> TradingResearchState:
    from ctrader_client import get_ctrader_multi_period_trendbars  # lazy import
    ctrader_config = state.config.get("data", {}).get("ctrader", {})
    min_abs_move_pct = float(ctrader_config.get("min_abs_move_pct", 0.15))
    min_range_pct = float(ctrader_config.get("min_range_pct", 0.25))
    fallback_periods = [str(period).upper() for period in ctrader_config.get("fallback_periods", [])]
    if not fallback_periods:
        fallback_periods = [str(ctrader_config.get("trendbar_period", "H1")).upper()]

    result = get_ctrader_multi_period_trendbars(period_names=fallback_periods)
    period_summaries = []
    selected_period = None
    selected_scored_candidates = []

    for period_name in fallback_periods:
        period_payload = result.get("periods", {}).get(period_name, {})
        scored_candidates = []
        for symbol_name, payload in period_payload.get("symbols", {}).items():
            candidate_payload = _build_ctrader_candidate(
                state=state,
                symbol_name=symbol_name,
                payload=payload,
                period_name=period_name,
                account_id=result.get("account_id"),
                min_abs_move_pct=min_abs_move_pct,
                min_range_pct=min_range_pct,
            )
            if candidate_payload is None:
                continue
            scored_candidates.append(candidate_payload)

        period_summaries.append({"period": period_name, "candidate_count": len(scored_candidates)})
        if scored_candidates:
            selected_period = period_name
            selected_scored_candidates = scored_candidates
            break

    candidates = [
        candidate
        for _, candidate in sorted(selected_scored_candidates, key=lambda item: item[0], reverse=True)
    ]
    state.config.setdefault("_runtime", {})["ctrader_selected_period"] = selected_period
    state.config.setdefault("_runtime", {})["ctrader_period_summaries"] = period_summaries
    state.raw_candidates = candidates[: state.max_candidates]
    return state


def _build_ctrader_candidate(
    state: TradingResearchState,
    symbol_name: str,
    payload: dict,
    period_name: str,
    account_id: object,
    min_abs_move_pct: float,
    min_range_pct: float,
):
    trendbars = payload.get("trendbars", [])
    if len(trendbars) < 2:
        return None
    first = trendbars[0]
    closes = [int(bar["close_raw"]) for bar in trendbars if int(bar.get("close_raw") or 0) > 0]
    highs = [int(bar["high_raw"]) for bar in trendbars if int(bar.get("high_raw") or 0) > 0]
    lows = [int(bar["low_raw"]) for bar in trendbars if int(bar.get("low_raw") or 0) > 0]
    if not closes or not highs or not lows:
        return None

    first_close = int(first["close_raw"])
    last_close = int(trendbars[-1]["close_raw"])
    previous_close = int(trendbars[-2]["close_raw"])
    move_pct = ((last_close / first_close) - 1.0) * 100.0 if first_close else 0.0
    last_bar_move_pct = ((last_close / previous_close) - 1.0) * 100.0 if previous_close else 0.0
    range_pct = ((max(highs) / min(lows)) - 1.0) * 100.0 if min(lows) else 0.0

    if abs(move_pct) < min_abs_move_pct and range_pct < min_range_pct:
        return None

    direction_hint = "upside momentum" if move_pct >= 0 else "downside momentum"
    candidate = MarketCandidate(
        asset=symbol_name,
        market="ctrader",
        reason=(
            f"cTrader trendbars show {direction_hint}: "
            f"{move_pct:.3f}% lookback move, {last_bar_move_pct:.3f}% last-bar move, "
            f"{range_pct:.3f}% lookback range, period={period_name}."
        ),
        catalyst_type="price_action",
        timeframe=state.timeframe,
        source_hint=f"cTrader Open API account {account_id}",
        metrics={
            "period": period_name,
            "move_pct": round(move_pct, 4),
            "last_bar_move_pct": round(last_bar_move_pct, 4),
            "range_pct": round(range_pct, 4),
            "trendbar_count": len(trendbars),
            "scan_score": round(abs(move_pct) + range_pct, 4),
        },
    )
    return abs(move_pct) + range_pct, candidate


def _alpaca_available(config: dict) -> bool:
    """Lazy wrapper so market_data is only imported when needed."""
    try:
        from market_data import alpaca_available
        return alpaca_available(config)
    except ImportError:
        return False


def autonomous_scan(state: TradingResearchState) -> TradingResearchState:
    """
    MVP scanner with provider selection.

    - mock: deterministic fake candidates.
    - alpaca: real historical stock bars, no order execution.
    - auto: Alpaca when credentials are found, otherwise mock.
    """
    provider = str(state.config.get("data", {}).get("provider", "mock")).lower()

    if provider == "alpaca":
        return _alpaca_scan(state)

    if provider == "ctrader":
        state.config.setdefault("_runtime", {})["provider_used"] = "ctrader"
        return _ctrader_scan(state)

    if provider == "auto" and _alpaca_available(state.config):
        try:
            state.config.setdefault("_runtime", {})["provider_used"] = "alpaca"
            return _alpaca_scan(state)
        except Exception as exc:  # noqa: BLE001 - fallback is intentional for MVP
            state.errors.append(f"alpaca_scan_fallback_to_mock: {exc}")
            state.config.setdefault("_runtime", {})["provider_used"] = "mock"
            return _mock_scan(state)

    state.config.setdefault("_runtime", {})["provider_used"] = "mock"
    return _mock_scan(state)
