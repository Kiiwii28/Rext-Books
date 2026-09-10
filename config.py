"""Configuration and secret loading for Rextbooks.

Secrets live in a local ``.env`` file (gitignored). Never hardcode the API key
and never expose it to the browser.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")

BOOKS_DIR = Path(os.getenv("BOOKS_DIR", BASE_DIR / "books"))
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

# Total characters of "extra context" / Spark source material sent to the model.
# DeepSeek v4 has a 1M-token window, so this can be large. Env-overridable.
CONTEXT_CHAR_BUDGET = int(os.getenv("REXTBOOKS_CONTEXT_CHARS", "400000"))

# Network timeouts (seconds) for the DeepSeek call: (connect, read).
DEEPSEEK_TIMEOUT = (10, 300)


def require_api_key() -> str:
    """Return the DeepSeek API key or raise a clear error if it is missing."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return DEEPSEEK_API_KEY
