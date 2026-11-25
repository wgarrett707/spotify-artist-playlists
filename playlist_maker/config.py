"""Load settings from environment variables, falling back to the project's .env file."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
TOKEN_FILE = PROJECT_DIR / ".spotify_token.json"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get(key: str, default: str = "") -> str:
    value = os.environ.get(key, default)
    return "" if value.startswith("paste-") else value  # ignore unfilled placeholders


def get_settings() -> dict:
    _load_env_file(ENV_FILE)
    return {
        "client_id": _get("SPOTIFY_CLIENT_ID"),
        "client_secret": _get("SPOTIFY_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
        "refresh_token": os.environ.get("SPOTIFY_REFRESH_TOKEN") or None,
    }
