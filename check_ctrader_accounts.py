from __future__ import annotations

from ctrader_client import list_ctrader_accounts


def main() -> None:
    accounts = list_ctrader_accounts()
    print(f"Found {len(accounts)} cTrader account(s).")
    for account in accounts:
        account_type = "live" if account.get("is_live") else "demo"
        print(
            "- "
            f"ctid_trader_account_id={account.get('ctid_trader_account_id')} "
            f"type={account_type} "
            f"trader_login={account.get('trader_login')}"
        )


if __name__ == "__main__":
    main()

