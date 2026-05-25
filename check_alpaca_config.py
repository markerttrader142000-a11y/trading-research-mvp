from __future__ import annotations

from pathlib import Path
import json

from config import load_config
from market_data import get_data_provider_status, load_alpaca_credentials


def mask(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def main() -> None:
    config = load_config()
    status = get_data_provider_status(config)
    print("Provider status:")
    for key, value in status.items():
        print(f"- {key}: {value}")

    alpaca_config = config.get("data", {}).get("alpaca", {})
    print("\nSelected Alpaca account config:")
    print(f"- account_label: {alpaca_config.get('account_label')}")
    print(f"- account_id_hint: {alpaca_config.get('account_id_hint')}")
    print(f"- trading_endpoint: {alpaca_config.get('trading_endpoint')}")
    print(f"- paper: {alpaca_config.get('paper')}")

    print("\nCredential paths checked:")
    for raw_path in config.get("data", {}).get("alpaca", {}).get("credential_paths", []):
        path = Path(str(raw_path)).expanduser()
        if path.exists():
            kind = "directory" if path.is_dir() else "file"
            print(f"- FOUND {kind}: {path}")
        else:
            print(f"- missing: {path}")

    print("\nVisible credential-like key names, values hidden:")
    for raw_path in config.get("data", {}).get("alpaca", {}).get("credential_paths", []):
        path = Path(str(raw_path)).expanduser()
        files = []
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = [child for child in path.iterdir() if child.is_file()]
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found_keys = []
            if file_path.suffix.lower() == ".json":
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {}
                if isinstance(payload, dict):
                    def walk(prefix, value):
                        if isinstance(value, dict):
                            for child_key, child_value in value.items():
                                walk(f"{prefix}.{child_key}" if prefix else str(child_key), child_value)
                        else:
                            key_lower = prefix.lower()
                            if any(token in key_lower for token in ["alpaca", "api", "key", "secret"]):
                                found_keys.append(prefix)
                    walk("", payload)
            else:
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    if "=" in line:
                        key = line.split("=", 1)[0].strip()
                        key_lower = key.lower()
                        if any(token in key_lower for token in ["alpaca", "api", "key", "secret"]):
                            found_keys.append(key)
            if found_keys:
                print(f"- {file_path}: {', '.join(found_keys)}")

    credentials = load_alpaca_credentials(config)
    print("\nCredentials:")
    if credentials is None:
        print("- Alpaca credentials not detected.")
    else:
        api_key, api_secret = credentials
        print(f"- API key: {mask(api_key)}")
        print(f"- API secret: {mask(api_secret)}")


if __name__ == "__main__":
    main()
