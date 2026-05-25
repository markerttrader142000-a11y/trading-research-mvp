from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import PROJECT_ROOT, load_config
from ctrader_auth import get_ctrader_settings


def load_ctrader_tokens(config: Dict[str, Any]) -> Dict[str, Any]:
    token_path = Path(config.get("data", {}).get("ctrader", {}).get("token_path", ".ctrader_tokens.json"))
    if not token_path.is_absolute():
        token_path = PROJECT_ROOT / token_path
    if not token_path.exists():
        raise FileNotFoundError(f"cTrader token file not found: {token_path}. Run python3 ctrader_auth.py first.")
    tokens = json.loads(token_path.read_text(encoding="utf-8"))
    if "accessToken" not in tokens:
        raise RuntimeError(f"cTrader token file does not contain accessToken: {token_path}")
    return tokens


def _account_to_dict(account: Any) -> Dict[str, Any]:
    return {
        "ctid_trader_account_id": getattr(account, "ctidTraderAccountId", None),
        "is_live": getattr(account, "isLive", None),
        "trader_login": getattr(account, "traderLogin", None),
        "last_closing_deal_timestamp": getattr(account, "lastClosingDealTimestamp", None),
        "last_balance_update_timestamp": getattr(account, "lastBalanceUpdateTimestamp", None),
    }


def _extract_response(response: Any) -> Any:
    from ctrader_open_api import Protobuf

    if hasattr(response, "payloadType") and not hasattr(response, "ctidTraderAccount"):
        try:
            return Protobuf.extract(response)
        except Exception:  # noqa: BLE001 - return original if already extracted/unknown
            return response
    return response


def _symbol_to_dict(symbol: Any) -> Dict[str, Any]:
    return {
        "symbol_id": getattr(symbol, "symbolId", None),
        "symbol_name": getattr(symbol, "symbolName", None),
        "enabled": getattr(symbol, "enabled", None),
        "base_asset_id": getattr(symbol, "baseAssetId", None),
        "quote_asset_id": getattr(symbol, "quoteAssetId", None),
        "symbol_category_id": getattr(symbol, "symbolCategoryId", None),
        "description": getattr(symbol, "description", None),
    }


def _pick_account_id(accounts: List[Dict[str, Any]], configured_account_id: Optional[Any] = None) -> int:
    if configured_account_id:
        return int(configured_account_id)
    demo_accounts = [account for account in accounts if not account.get("is_live")]
    selected = demo_accounts[0] if demo_accounts else accounts[0]
    return int(selected["ctid_trader_account_id"])


def _trendbar_to_dict(trendbar: Any) -> Dict[str, Any]:
    low = int(getattr(trendbar, "low", 0))
    delta_open = int(getattr(trendbar, "deltaOpen", 0))
    delta_close = int(getattr(trendbar, "deltaClose", 0))
    delta_high = int(getattr(trendbar, "deltaHigh", 0))
    return {
        "timestamp_minutes": getattr(trendbar, "utcTimestampInMinutes", None),
        "low_raw": low,
        "open_raw": low + delta_open,
        "close_raw": low + delta_close,
        "high_raw": low + delta_high,
        "volume": getattr(trendbar, "volume", None),
    }


def list_ctrader_accounts(timeout_seconds: int = 15) -> List[Dict[str, Any]]:
    """
    Read-only cTrader account discovery.

    Sends:
    1. ProtoOAApplicationAuthReq
    2. ProtoOAGetAccountListByAccessTokenReq

    It does not request trading scope by itself and does not send orders.
    """
    from ctrader_open_api import Client, EndPoints, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
    )
    from twisted.internet import defer, reactor

    config = load_config()
    settings = get_ctrader_settings(config)
    tokens = load_ctrader_tokens(config)
    environment = str(config.get("data", {}).get("ctrader", {}).get("environment", "demo")).lower()
    host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST

    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    result: Dict[str, Any] = {"accounts": [], "error": None}

    @defer.inlineCallbacks
    def workflow():
        try:
            yield client.send(
                ProtoOAApplicationAuthReq(
                    clientId=settings["client_id"],
                    clientSecret=settings["client_secret"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            response = yield client.send(
                ProtoOAGetAccountListByAccessTokenReq(
                    accessToken=tokens["accessToken"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            response = _extract_response(response)
            result["accounts"] = [_account_to_dict(account) for account in response.ctidTraderAccount]
        except Exception as exc:  # noqa: BLE001 - CLI should surface readable error
            result["error"] = repr(exc)
        finally:
            try:
                client.stopService()
            finally:
                reactor.stop()

    reactor.callWhenRunning(workflow)
    client.startService()
    reactor.run()

    if result["error"]:
        raise RuntimeError(f"cTrader account listing failed: {result['error']}")
    return result["accounts"]


def list_ctrader_symbols(account_id: Optional[int] = None, timeout_seconds: int = 20) -> Dict[str, Any]:
    """
    Lists enabled symbols for a demo/live account in read-only mode.
    """
    from ctrader_open_api import Client, EndPoints, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAAccountAuthReq,
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOASymbolsListReq,
    )
    from twisted.internet import defer, reactor

    config = load_config()
    settings = get_ctrader_settings(config)
    tokens = load_ctrader_tokens(config)
    ctrader_config = config.get("data", {}).get("ctrader", {})
    environment = str(ctrader_config.get("environment", "demo")).lower()
    host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
    configured_account_id = account_id or ctrader_config.get("default_account_id")

    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    result: Dict[str, Any] = {"account_id": None, "symbols": [], "error": None}

    @defer.inlineCallbacks
    def workflow():
        try:
            yield client.send(
                ProtoOAApplicationAuthReq(
                    clientId=settings["client_id"],
                    clientSecret=settings["client_secret"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = yield client.send(
                ProtoOAGetAccountListByAccessTokenReq(accessToken=tokens["accessToken"]),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = _extract_response(accounts_response)
            accounts = [_account_to_dict(account) for account in accounts_response.ctidTraderAccount]
            selected_account_id = _pick_account_id(accounts, configured_account_id)
            result["account_id"] = selected_account_id

            yield client.send(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=selected_account_id,
                    accessToken=tokens["accessToken"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = yield client.send(
                ProtoOASymbolsListReq(
                    ctidTraderAccountId=selected_account_id,
                    includeArchivedSymbols=False,
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = _extract_response(symbols_response)
            result["symbols"] = [_symbol_to_dict(symbol) for symbol in symbols_response.symbol]
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        finally:
            try:
                client.stopService()
            finally:
                reactor.stop()

    reactor.callWhenRunning(workflow)
    client.startService()
    reactor.run()

    if result["error"]:
        raise RuntimeError(f"cTrader symbol listing failed: {result['error']}")
    return result


def get_ctrader_trendbars(symbol_names: Optional[List[str]] = None, timeout_seconds: int = 25) -> Dict[str, Any]:
    """
    Fetches raw trendbars for configured symbol names.

    Prices are returned as raw integer values from cTrader trendbars. This is
    enough for momentum/range calculations; price formatting can be added later
    using detailed symbol metadata.
    """
    from ctrader_open_api import Client, EndPoints, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAAccountAuthReq,
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAGetTrendbarsReq,
        ProtoOASymbolsListReq,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    from twisted.internet import defer, reactor

    config = load_config()
    settings = get_ctrader_settings(config)
    tokens = load_ctrader_tokens(config)
    ctrader_config = config.get("data", {}).get("ctrader", {})
    environment = str(ctrader_config.get("environment", "demo")).lower()
    host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
    configured_account_id = ctrader_config.get("default_account_id")
    target_names = [name.upper() for name in (symbol_names or ctrader_config.get("symbol_names", []))]
    period_name = str(ctrader_config.get("trendbar_period", "H1")).upper()
    count = int(ctrader_config.get("trendbar_count", 50))
    now_ms = int(time.time() * 1000)
    lookback_ms = 1000 * 60 * 60 * 24 * 14

    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    result: Dict[str, Any] = {"account_id": None, "period": period_name, "symbols": {}, "missing_symbols": [], "error": None}

    @defer.inlineCallbacks
    def workflow():
        try:
            yield client.send(
                ProtoOAApplicationAuthReq(
                    clientId=settings["client_id"],
                    clientSecret=settings["client_secret"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = yield client.send(
                ProtoOAGetAccountListByAccessTokenReq(accessToken=tokens["accessToken"]),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = _extract_response(accounts_response)
            accounts = [_account_to_dict(account) for account in accounts_response.ctidTraderAccount]
            selected_account_id = _pick_account_id(accounts, configured_account_id)
            result["account_id"] = selected_account_id

            yield client.send(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=selected_account_id,
                    accessToken=tokens["accessToken"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = yield client.send(
                ProtoOASymbolsListReq(
                    ctidTraderAccountId=selected_account_id,
                    includeArchivedSymbols=False,
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = _extract_response(symbols_response)
            symbols = {_symbol_to_dict(symbol)["symbol_name"].upper(): _symbol_to_dict(symbol) for symbol in symbols_response.symbol}

            period = ProtoOATrendbarPeriod.Value(period_name)
            for name in target_names:
                symbol = symbols.get(name)
                if not symbol:
                    result["missing_symbols"].append(name)
                    continue
                bars_response = yield client.send(
                    ProtoOAGetTrendbarsReq(
                        ctidTraderAccountId=selected_account_id,
                        symbolId=int(symbol["symbol_id"]),
                        period=period,
                        fromTimestamp=now_ms - lookback_ms,
                        toTimestamp=now_ms,
                        count=count,
                    ),
                    responseTimeoutInSeconds=timeout_seconds,
                )
                bars_response = _extract_response(bars_response)
                trendbars = [_trendbar_to_dict(bar) for bar in bars_response.trendbar]
                result["symbols"][name] = {
                    "symbol": symbol,
                    "trendbars": trendbars,
                    "trendbar_count": len(trendbars),
                }
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        finally:
            try:
                client.stopService()
            finally:
                reactor.stop()

    reactor.callWhenRunning(workflow)
    client.startService()
    reactor.run()

    if result["error"]:
        raise RuntimeError(f"cTrader trendbar fetch failed: {result['error']}")
    return result


def get_ctrader_multi_period_trendbars(
    period_names: Optional[List[str]] = None,
    symbol_names: Optional[List[str]] = None,
    timeout_seconds: int = 35,
) -> Dict[str, Any]:
    """
    Fetches trendbars for several periods in a single cTrader/Twisted session.

    This avoids restarting the Twisted reactor multiple times in one Python
    process, which is not supported.
    """
    from ctrader_open_api import Client, EndPoints, TcpProtocol
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAAccountAuthReq,
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAGetTrendbarsReq,
        ProtoOASymbolsListReq,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    from twisted.internet import defer, reactor

    config = load_config()
    settings = get_ctrader_settings(config)
    tokens = load_ctrader_tokens(config)
    ctrader_config = config.get("data", {}).get("ctrader", {})
    environment = str(ctrader_config.get("environment", "demo")).lower()
    host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
    configured_account_id = ctrader_config.get("default_account_id")
    target_names = [name.upper() for name in (symbol_names or ctrader_config.get("symbol_names", []))]
    periods = [name.upper() for name in (period_names or ctrader_config.get("fallback_periods", []))]
    if not periods:
        periods = [str(ctrader_config.get("trendbar_period", "H1")).upper()]
    count = int(ctrader_config.get("trendbar_count", 50))
    now_ms = int(time.time() * 1000)
    lookback_ms = 1000 * 60 * 60 * 24 * 30

    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    result: Dict[str, Any] = {
        "account_id": None,
        "periods": {},
        "target_symbols": target_names,
        "error": None,
    }

    @defer.inlineCallbacks
    def workflow():
        try:
            yield client.send(
                ProtoOAApplicationAuthReq(
                    clientId=settings["client_id"],
                    clientSecret=settings["client_secret"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = yield client.send(
                ProtoOAGetAccountListByAccessTokenReq(accessToken=tokens["accessToken"]),
                responseTimeoutInSeconds=timeout_seconds,
            )
            accounts_response = _extract_response(accounts_response)
            accounts = [_account_to_dict(account) for account in accounts_response.ctidTraderAccount]
            selected_account_id = _pick_account_id(accounts, configured_account_id)
            result["account_id"] = selected_account_id

            yield client.send(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=selected_account_id,
                    accessToken=tokens["accessToken"],
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = yield client.send(
                ProtoOASymbolsListReq(
                    ctidTraderAccountId=selected_account_id,
                    includeArchivedSymbols=False,
                ),
                responseTimeoutInSeconds=timeout_seconds,
            )
            symbols_response = _extract_response(symbols_response)
            symbols = {
                _symbol_to_dict(symbol)["symbol_name"].upper(): _symbol_to_dict(symbol)
                for symbol in symbols_response.symbol
            }

            for period_name in periods:
                period_payload: Dict[str, Any] = {
                    "period": period_name,
                    "symbols": {},
                    "missing_symbols": [],
                }
                period = ProtoOATrendbarPeriod.Value(period_name)
                for name in target_names:
                    symbol = symbols.get(name)
                    if not symbol:
                        period_payload["missing_symbols"].append(name)
                        continue
                    bars_response = yield client.send(
                        ProtoOAGetTrendbarsReq(
                            ctidTraderAccountId=selected_account_id,
                            symbolId=int(symbol["symbol_id"]),
                            period=period,
                            fromTimestamp=now_ms - lookback_ms,
                            toTimestamp=now_ms,
                            count=count,
                        ),
                        responseTimeoutInSeconds=timeout_seconds,
                    )
                    bars_response = _extract_response(bars_response)
                    trendbars = [_trendbar_to_dict(bar) for bar in bars_response.trendbar]
                    period_payload["symbols"][name] = {
                        "symbol": symbol,
                        "trendbars": trendbars,
                        "trendbar_count": len(trendbars),
                    }
                result["periods"][period_name] = period_payload
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        finally:
            try:
                client.stopService()
            finally:
                reactor.stop()

    reactor.callWhenRunning(workflow)
    client.startService()
    reactor.run()

    if result["error"]:
        raise RuntimeError(f"cTrader multi-period trendbar fetch failed: {result['error']}")
    return result


if __name__ == "__main__":
    accounts = list_ctrader_accounts()
    print(json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2))
