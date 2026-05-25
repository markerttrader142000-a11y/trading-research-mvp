from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"


def _load_dotenv_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _flatten_json_keys(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Pulls likely Alpaca credentials from common JSON config structures without
    assuming a specific schema.
    """
    flattened: Dict[str, str] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                next_prefix = f"{prefix}_{child_key}" if prefix else str(child_key)
                walk(next_prefix, child_value)
        elif isinstance(value, str):
            flattened[prefix.upper()] = value

    walk("", data)
    return flattened


def _load_config_directory(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists() or not path.is_dir():
        return values

    for child in path.iterdir():
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        if child.suffix.lower() == ".json":
            values.update(_load_json_file(child))
        else:
            values.update(_load_dotenv_file(child))
    return values


def _load_json_file(path: Path) -> Dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return _flatten_json_keys(data)


def load_alpaca_credentials(config: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    Looks for Alpaca credentials in:
    1. environment variables;
    2. configured .env/JSON paths.

    This function never prints or returns credentials except to the caller.
    """
    candidates: Dict[str, str] = dict(os.environ)

    alpaca_config = config.get("data", {}).get("alpaca", {})
    for raw_path in alpaca_config.get("credential_paths", []):
        path = Path(str(raw_path)).expanduser()
        if path.is_dir():
            candidates.update(_load_config_directory(path))
            continue
        if path.suffix.lower() == ".json":
            candidates.update(_load_json_file(path))
        else:
            candidates.update(_load_dotenv_file(path))

    def normalize(name: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", name.upper())

    normalized_candidates = {
        normalize(name): value for name, value in candidates.items() if isinstance(value, str) and value.strip()
    }

    key_names = {
        "ALPACAAPIKEY",
        "ALPACAAPIKEYID",
        "APCAAPIKEYID",
        "ALPACAKEYID",
        "ALPACAKEY",
        "APIKEY",
        "APIKEYID",
        "KEYID",
        "KEY",
        "PAPERAPIKEY",
        "PAPERAPIKEYID",
        "PAPERKEYID",
        "PAPERKEY",
        "ALPACAPAPERAPIKEY",
        "ALPACAPAPERAPIKEYID",
        "ALPACAPAPERKEYID",
        "ALPACAPAPERKEY",
    }
    secret_names = {
        "ALPACAAPISECRET",
        "ALPACAAPISECRETKEY",
        "APCAAPISECRETKEY",
        "ALPACASECRETKEY",
        "ALPACASECRET",
        "APISECRET",
        "APISECRETKEY",
        "SECRETKEY",
        "SECRET",
        "PAPERAPISECRET",
        "PAPERAPISECRETKEY",
        "PAPERSECRETKEY",
        "PAPERSECRET",
        "ALPACAPAPERAPISECRET",
        "ALPACAPAPERAPISECRETKEY",
        "ALPACAPAPERSECRETKEY",
        "ALPACAPAPERSECRET",
    }

    api_key = next((normalized_candidates[name] for name in key_names if normalized_candidates.get(name)), None)
    api_secret = next((normalized_candidates[name] for name in secret_names if normalized_candidates.get(name)), None)

    if not api_key:
        api_key = next(
            (
                value
                for name, value in normalized_candidates.items()
                if name.endswith("KEYID") or name.endswith("APIKEY") or name.endswith("PAPERKEY")
            ),
            None,
        )

    if not api_secret:
        api_secret = next(
            (
                value
                for name, value in normalized_candidates.items()
                if name.endswith("SECRETKEY") or name.endswith("APISECRET") or name.endswith("PAPERSECRET")
            ),
            None,
        )

    if api_key and api_secret:
        return api_key, api_secret
    return None


def fetch_alpaca_stock_bars(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    alpaca_config = config.get("data", {}).get("alpaca", {})
    credentials = load_alpaca_credentials(config)
    if credentials is None:
        raise RuntimeError("Alpaca credentials not found in environment or configured credential paths.")

    api_key, api_secret = credentials
    symbols = alpaca_config.get("symbols", [])
    if not symbols:
        raise RuntimeError("No Alpaca symbols configured.")

    max_symbols = int(alpaca_config.get("max_symbols", 20))
    symbols = [str(symbol).upper() for symbol in symbols[:max_symbols]]
    lookback_days = int(alpaca_config.get("lookback_days", 30))
    timeframe = str(alpaca_config.get("timeframe", "1Day"))
    feed = str(alpaca_config.get("feed", "iex"))

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    response = requests.get(
        f"{ALPACA_DATA_BASE_URL}/v2/stocks/bars",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        },
        params={
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
            "adjustment": "raw",
            "feed": feed,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    bars_by_symbol = payload.get("bars", {})

    rows: List[Dict[str, Any]] = []
    for symbol, bars in bars_by_symbol.items():
        if not isinstance(bars, list) or len(bars) < 2:
            continue
        first = bars[0]
        last = bars[-1]
        previous = bars[-2]
        first_close = float(first["c"])
        last_close = float(last["c"])
        previous_close = float(previous["c"])
        move_pct = ((last_close / first_close) - 1.0) * 100.0
        day_move_pct = ((last_close / previous_close) - 1.0) * 100.0
        high = max(float(bar["h"]) for bar in bars)
        low = min(float(bar["l"]) for bar in bars)
        range_pct = ((high / low) - 1.0) * 100.0 if low else 0.0
        volume = sum(float(bar.get("v", 0.0)) for bar in bars)

        rows.append(
            {
                "symbol": symbol,
                "first_close": round(first_close, 4),
                "last_close": round(last_close, 4),
                "move_pct": round(move_pct, 2),
                "day_move_pct": round(day_move_pct, 2),
                "range_pct": round(range_pct, 2),
                "volume": round(volume, 0),
                "bars": len(bars),
            }
        )

    return rows


def alpaca_available(config: Dict[str, Any]) -> bool:
    return load_alpaca_credentials(config) is not None


def get_data_provider_status(config: Dict[str, Any]) -> Dict[str, Any]:
    configured_provider = str(config.get("data", {}).get("provider", "mock")).lower()
    has_alpaca_credentials = alpaca_available(config)
    provider_used = configured_provider if configured_provider in {"alpaca", "ctrader"} else "mock"
    if configured_provider == "auto":
        provider_used = "alpaca" if has_alpaca_credentials else "mock"

    return {
        "configured_provider": configured_provider,
        "provider_used": provider_used,
        "alpaca_credentials_detected": has_alpaca_credentials,
    }
