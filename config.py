"""Configuration and secret loading for Rextbooks.

The DeepSeek API key can come from (in priority order):
  1. a key entered through the app's own Settings UI, persisted to
     ``local_settings.json`` next to the app — no file editing, no
     restart needed. This is what a packaged .exe hands to a non-technical
     user: they paste a key into Settings once and it just works.
  2. a local ``.env`` file (gitignored) or an environment variable — the
     developer-friendly path when running from source.

The key is never sent back to the browser once saved (the Settings UI only
ever learns whether one is configured, not its value).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv


def _app_dir() -> Path:
    """The folder holding the app's own persistent local data (books,
    settings, .env). When frozen with PyInstaller, ``__file__`` lives inside
    a temporary extraction directory that's recreated on every launch, so
    that can't be where user data lives — use the .exe's own folder instead,
    which is stable across runs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _app_dir()

load_dotenv(BASE_DIR / ".env")

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")

BOOKS_DIR = Path(os.getenv("BOOKS_DIR", BASE_DIR / "books"))
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

# Total characters of "extra context" / Spark source material sent to the model.
# DeepSeek v4 has a 1M-token window, so this can be large. Env-overridable.
CONTEXT_CHAR_BUDGET = int(os.getenv("REXTBOOKS_CONTEXT_CHARS", "400000"))

# Network timeouts (seconds) for the DeepSeek call: (connect, read).
DEEPSEEK_TIMEOUT = (10, 300)


# --------------------------------------------------------------------------- #
#  API key                                                                     #
# --------------------------------------------------------------------------- #

_SETTINGS_FILE = BASE_DIR / "local_settings.json"
_ENV_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
_lock = threading.Lock()


def _read_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_settings(data: dict) -> None:
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_FILE)


def get_api_key() -> str:
    """The key actually in effect: a Settings-UI key if one is saved,
    otherwise the .env / environment value."""
    with _lock:
        ui_key = (_read_settings().get("deepseekApiKey") or "").strip()
    return ui_key or _ENV_API_KEY


def api_key_source() -> str:
    """Where the active key (if any) came from: "settings", "env", or "none"."""
    with _lock:
        ui_key = (_read_settings().get("deepseekApiKey") or "").strip()
    if ui_key:
        return "settings"
    if _ENV_API_KEY:
        return "env"
    return "none"


def set_api_key(key: str) -> None:
    """Save a key entered in Settings, or clear it (empty string) to fall
    back to .env / the environment, if either is set."""
    with _lock:
        data = _read_settings()
        key = (key or "").strip()
        if key:
            data["deepseekApiKey"] = key
        else:
            data.pop("deepseekApiKey", None)
        _write_settings(data)


def require_api_key() -> str:
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "No DeepSeek API key configured yet. Add one in ⚙ Settings to start generating."
        )
    return key


# --------------------------------------------------------------------------- #
#  Author (shown on exported PDFs/EPUBs; set from ⚙ Settings)                  #
# --------------------------------------------------------------------------- #

def get_author() -> str:
    with _lock:
        return (_read_settings().get("author") or "").strip()


def set_author(name: str) -> None:
    with _lock:
        data = _read_settings()
        name = (name or "").strip()
        if name:
            data["author"] = name
        else:
            data.pop("author", None)
        _write_settings(data)


# --------------------------------------------------------------------------- #
#  Pexels API key (optional — powers the image-search tab's stock-photo       #
#  fallback; Wikimedia Commons search works with no key at all)               #
# --------------------------------------------------------------------------- #
#
# STUB: get a free key at https://www.pexels.com/api/ and paste it into
# ⚙ Settings, or set PEXELS_API_KEY in a local .env file. Same precedence and
# storage as the DeepSeek key above (Settings-UI value wins over .env/env).

_ENV_PEXELS_KEY = os.getenv("PEXELS_API_KEY", "").strip()


def get_pexels_key() -> str:
    with _lock:
        ui_key = (_read_settings().get("pexelsApiKey") or "").strip()
    return ui_key or _ENV_PEXELS_KEY


def set_pexels_key(key: str) -> None:
    with _lock:
        data = _read_settings()
        key = (key or "").strip()
        if key:
            data["pexelsApiKey"] = key
        else:
            data.pop("pexelsApiKey", None)
        _write_settings(data)
