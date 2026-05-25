from __future__ import annotations

from ctrader_client import list_ctrader_symbols


def main() -> None:
    result = list_ctrader_symbols()
    symbols = result["symbols"]
    print(f"Account: {result['account_id']}")
    print(f"Found {len(symbols)} enabled symbol(s). Showing first 50:")
    for symbol in symbols[:50]:
        print(
            "- "
            f"symbol_id={symbol.get('symbol_id')} "
            f"name={symbol.get('symbol_name')} "
            f"category_id={symbol.get('symbol_category_id')} "
            f"description={symbol.get('description')}"
        )


if __name__ == "__main__":
    main()

