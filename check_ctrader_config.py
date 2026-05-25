from __future__ import annotations

import json
from pathlib import Path

from config import PROJECT_ROOT, load_config
from ctrader_auth import get_ctrader_settings


def mask(value: str) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def main() -> None:
    config = load_config()
    settings = get_ctrader_settings(config)
    token_path = Path(config.get("data", {}).get("ctrader", {}).get("token_path", ".ctrader_tokens.json"))
    if not token_path.is_absolute():
        token_path = PROJECT_ROOT / token_path

    print("cTrader config:")
    print(f"- client_id: {mask(settings.get('client_id', ''))}")
    print(f"- client_secret: {mask(settings.get('client_secret', ''))}")
    print(f"- redirect_uri: {settings.get('redirect_uri') or 'missing'}")
    print(f"- scope: {settings.get('scope') or 'missing'}")
    print(f"- token_path: {token_path}")
    print(f"- token_file_exists: {token_path.exists()}")

    if token_path.exists():
        try:
            tokens = json.loads(token_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            tokens = {}
        print("- token_keys:", ", ".join(sorted(tokens.keys())) if tokens else "invalid_or_empty")


if __name__ == "__main__":
    main()

