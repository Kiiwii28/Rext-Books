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


def stream_chat(messages: list[dict], *, temperature: float = 0.7) -> Iterator[str]:
    """Yield text deltas from DeepSeek as they arrive.

    Raises ``requests.HTTPError`` on a non-2xx response (with the body attached
    to the exception message where possible).
    """
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
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


def chat(messages: list[dict], *, temperature: float = 0.7) -> str:
    """Non-streaming convenience wrapper."""
    return "".join(stream_chat(messages, temperature=temperature))
