"""Thin DeepSeek client.

DeepSeek exposes an OpenAI-compatible Chat Completions API. We only need two
things: a streaming call (for the UI) and a plain call (handy for short prompts).
"""

from __future__ import annotations

import json
from typing import Iterator

import requests

import config


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.require_api_key()}",
        "Content-Type": "application/json",
    }


def _endpoint() -> str:
    return f"{config.DEEPSEEK_BASE_URL}/chat/completions"


def stream_chat(messages: list[dict], *, temperature: float = 0.7,
                max_tokens: int | None = None,
                reasoning_effort: str | None = None) -> Iterator[str]:
    """Yield text deltas from DeepSeek as they arrive.

    ``reasoning_effort="none"`` skips this model's hidden reasoning pass
    entirely — worth knowing about: the model spends an unpredictable (and
    sometimes very large — 500+ tokens observed) number of hidden
    "reasoning_content" tokens before any visible output, even for a trivial
    one-word answer, and those count against ``max_tokens`` together with the
    real output. For a short, simple classification prompt this reliably
    produces the same answer using a single visible token instead, sidestepping
    the whole "was max_tokens big enough" question rather than just raising
    the cap and hoping.

    Raises ``requests.HTTPError`` on a non-2xx response (with the body attached
    to the exception message where possible).
    """
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    with requests.post(
        _endpoint(),
        headers=_headers(),
        json=payload,
        stream=True,
        timeout=config.DEEPSEEK_TIMEOUT,
    ) as resp:
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise requests.HTTPError(f"DeepSeek {resp.status_code}: {detail}", response=resp)

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield piece


def chat(messages: list[dict], *, temperature: float = 0.7,
         max_tokens: int | None = None, reasoning_effort: str | None = None) -> str:
    """Non-streaming convenience wrapper (still uses the streaming endpoint
    under the hood — just joins the pieces — since that's the one path
    already proven to work reliably against DeepSeek's API here)."""
    return "".join(stream_chat(messages, temperature=temperature, max_tokens=max_tokens,
                               reasoning_effort=reasoning_effort))


def test_key(key: str) -> tuple[bool, str]:
    """Make one minimal request to confirm a key actually works, so Settings
    can give immediate feedback instead of the user finding out mid-generation."""
    try:
        resp = requests.post(
            _endpoint(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": config.DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
                "stream": False,
            },
            timeout=(10, 20),
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    if resp.status_code >= 400:
        return False, f"DeepSeek rejected this key (HTTP {resp.status_code}): {resp.text[:200]}"
    return True, "Key works ✓"
