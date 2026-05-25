from __future__ import annotations

from ctrader_client import get_ctrader_trendbars


def _move_pct(first_close: int, last_close: int) -> float:
    if not first_close:
        return 0.0
    return round(((last_close / first_close) - 1.0) * 100.0, 4)


def main() -> None:
    result = get_ctrader_trendbars()
    print(f"Account: {result['account_id']}")
    print(f"Period: {result['period']}")
    if result["missing_symbols"]:
        print("Missing symbols:", ", ".join(result["missing_symbols"]))

    for name, payload in result["symbols"].items():
        trendbars = payload["trendbars"]
        print(f"\n{name}: {len(trendbars)} trendbar(s)")
        if not trendbars:
            continue
        first = trendbars[0]
        last = trendbars[-1]
        move = _move_pct(int(first["close_raw"]), int(last["close_raw"]))
        print(f"- first_close_raw={first['close_raw']}")
        print(f"- last_close_raw={last['close_raw']}")
        print(f"- move_pct_raw={move}")
        print(f"- last_volume={last['volume']}")


if __name__ == "__main__":
    main()

