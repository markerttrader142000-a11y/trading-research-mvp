from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from config import PROJECT_ROOT, load_config


CTRADER_AUTHORIZE_BASE_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
CTRADER_TOKEN_URL = "https://openapi.ctrader.com/apps/token"


def _load_dotenv(path: Path) -> Dict[str, str]:
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


def load_ctrader_env(config: Dict[str, Any]) -> Dict[str, str]:
    values: Dict[str, str] = dict(os.environ)
    for raw_path in config.get("data", {}).get("ctrader", {}).get("credential_paths", []):
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        values.update(_load_dotenv(path))
    return values


def get_ctrader_settings(config: Dict[str, Any]) -> Dict[str, str]:
    values = load_ctrader_env(config)
    ctrader_config = config.get("data", {}).get("ctrader", {})

    client_id = values.get("CTRADER_CLIENT_ID", "").strip()
    client_secret = values.get("CTRADER_CLIENT_SECRET", "").strip()
    redirect_uri = values.get("CTRADER_REDIRECT_URI", ctrader_config.get("redirect_uri", "")).strip()
    scope = values.get("CTRADER_SCOPE", ctrader_config.get("scope", "accounts")).strip()
    token_path = str(ctrader_config.get("token_path", ".ctrader_tokens.json"))

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "token_path": token_path,
    }


def build_authorize_url(settings: Dict[str, str]) -> str:
    params = {
        "client_id": settings["client_id"],
        "redirect_uri": settings["redirect_uri"],
        "scope": settings["scope"],
        "product": "web",
    }
    return CTRADER_AUTHORIZE_BASE_URL + "?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(settings: Dict[str, str], code: str) -> Dict[str, Any]:
    response = requests.get(
        CTRADER_TOKEN_URL,
        params={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings["redirect_uri"],
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def save_tokens(config: Dict[str, Any], tokens: Dict[str, Any]) -> Path:
    token_path = Path(str(config.get("data", {}).get("ctrader", {}).get("token_path", ".ctrader_tokens.json")))
    if not token_path.is_absolute():
        token_path = PROJECT_ROOT / token_path
    token_path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    return token_path


def _extract_port_from_redirect_uri(redirect_uri: str) -> int:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80


def run_local_oauth_flow(open_browser: bool = True, timeout_seconds: int = 120) -> Optional[Path]:
    config = load_config()
    settings = get_ctrader_settings(config)

    missing = [name for name in ["client_id", "client_secret", "redirect_uri"] if not settings.get(name)]
    if missing:
        raise RuntimeError(f"Missing cTrader settings: {', '.join(missing)}. Fill .env first.")

    redirect_uri = settings["redirect_uri"]
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    callback_path = parsed_redirect.path or "/callback"
    port = _extract_port_from_redirect_uri(redirect_uri)
    result: Dict[str, Optional[str]] = {"code": None, "error": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib method name
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            result["code"] = params.get("code", [None])[0]
            result["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"cTrader authorization received. You can return to the terminal."
            )

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            return

    server = HTTPServer(("localhost", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    authorize_url = build_authorize_url(settings)
    print("Open this URL to authorize cTrader access:")
    print(authorize_url)
    print(f"\nWaiting for redirect on {redirect_uri} ...")

    if open_browser:
        webbrowser.open(authorize_url)

    started = time.time()
    try:
        while time.time() - started < timeout_seconds:
            if result["code"] or result["error"]:
                break
            time.sleep(0.25)
    finally:
        server.shutdown()

    if result["error"]:
        raise RuntimeError(f"cTrader authorization error: {result['error']}")
    if not result["code"]:
        print("Timed out waiting for cTrader redirect.")
        return None

    tokens = exchange_code_for_tokens(settings, result["code"] or "")
    token_path = save_tokens(config, tokens)
    print(f"Saved cTrader tokens to: {token_path}")
    print("Token keys received:", ", ".join(sorted(tokens.keys())))
    return token_path


if __name__ == "__main__":
    run_local_oauth_flow()

