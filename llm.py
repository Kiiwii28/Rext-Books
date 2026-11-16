"""The chat client — one transport, any OpenAI-compatible provider.

DeepSeek and Gemini both expose the OpenAI Chat Completions wire format, so
there is exactly one request shape here. Which endpoint / model / key it is
aimed at comes from the active provider's preset in ``config.PROVIDERS``,
resolved per call (never baked in at import time) so switching provider in
⚙ Settings takes effect on the next request with no restart.

Two things here are deliberate provider guardrails rather than generic
plumbing:

* ``reasoning_effort``. DeepSeek accepts it, and ``"none"`` skips its hidden
  reasoning pass — which is why the short internal calls in images.py ask for
  it: without it, a ``max_tokens=50`` judge call can spend its whole budget
  thinking and return nothing. Gemini has no equivalent switch, so a caller's
  "don't think, just answer" intent is preserved two other ways instead —
  its preset's non-thinking ``utility_model`` for internal calls, and (for an
  explicit ``reasoning_effort="none"``) a raised visible-output budget. The
  parameter is therefore only ever sent to a provider whose preset says it
  understands it: nothing DeepSeek-specific leaks into a Gemini request, and
  nothing Gemini-specific (a forced utility model) leaks into a DeepSeek one.

* ``finish_reason`` inspection. A silent truncation ("length" / "MAX_TOKENS")
  or a safety block looks like "the model returned nothing" to a caller that
  only counts text deltas. The reason is surfaced through the optional
  ``meta`` dict so the caller can tell the user, and a block that produced no
  content at all raises a real error instead of an empty success.
"""

from __future__ import annotations

import json
from typing import Iterator

import requests

import config

# finish_reason values that mean "output was cut off", across providers —
# DeepSeek/OpenAI use "length"; Gemini's OpenAI layer reports "MAX_TOKENS".
_TRUNCATED_REASONS = {r.lower() for r in (
    "length", "max_tokens", "max_output_tokens", "MAX_TOKENS",
)}

# finish_reason values that mean "a safety/policy layer stopped this".
_BLOCKED_REASONS = {r.lower() for r in (
    "content_filter", "safety", "recitation", "prohibited_content",
    "blocklist", "spii", "SAFETY", "RECITATION", "PROHIBITED_CONTENT",
    "BLOCKLIST", "SPII",
)}

# Visible-output floor applied when a caller asked for "no hidden thinking"
# on a provider that has no reasoning_effort switch. Generous on purpose: this
# is a cap, not a cost (only the tokens actually produced are billed), and a
# thinking model's hidden pass can easily exceed a few hundred tokens — which
# is exactly the failure this guards against (an empty reply to a 50-token
# judge call). Gemini is the provider that needs it.
_UTILITY_TOKEN_FLOOR = 1024

# Non-streaming key test: a thinking model can take a while before its first
# visible token, and a non-streaming request waits for the whole reply. 30s
# proved too tight in practice (a real Test key on Gemini timed out at 30s).
_TEST_TIMEOUT = (10, 90)


def _endpoint(profile: dict) -> str:
    return f"{profile['base_url']}/chat/completions"


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _error_detail(resp: requests.Response) -> str:
    """A readable message from an error body. Google (and OpenAI/DeepSeek)
    nest it under ``error.message``; Gemini sometimes wraps the whole object
    in a one-element list instead of an object, so unwrap that too. Falls back
    to raw text for anything unexpected."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:500]
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:500]
        if isinstance(err, str):
            return err[:500]
    return resp.text[:500]


def _build_payload(profile: dict, messages: list[dict], *, model: str,
                   temperature: float, max_tokens: int | None,
                   reasoning_effort: str | None, stream: bool) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        if profile["supports_reasoning_effort"]:
            payload["reasoning_effort"] = reasoning_effort
        elif reasoning_effort.lower() in ("none", "minimal"):
            # "Skip the hidden thinking" — this provider can't be told that
            # directly, so make the visible budget big enough that a thinking
            # pass (if the model has one anyway) can't starve the answer.
            payload["max_tokens"] = max(payload.get("max_tokens") or 0,
                                        _UTILITY_TOKEN_FLOOR)
    return payload


def stream_chat(messages: list[dict], *, temperature: float = 0.7,
                max_tokens: int | None = None,
                reasoning_effort: str | None = None,
                provider: str | None = None,
                model: str | None = None,
                utility: bool = False,
                meta: dict | None = None) -> Iterator[str]:
    """Yield text deltas from the active provider as they arrive.

    ``utility=True`` marks a short internal call (image judging, query
    rewriting): it uses the provider's cheapest non-thinking model and asks
    for no hidden reasoning. ``meta``, if given, is filled in when the stream
    ends with what the provider reported (``finish_reason``, ``truncated``,
    ``blocked``) so callers can warn about cut-off output.

    Raises ``requests.HTTPError`` on a non-2xx response, and ``RuntimeError``
    when a provider blocks the response outright or reports an in-band error.
    """
    profile = config.llm_profile(provider)
    label = profile["label"]

    if utility and reasoning_effort is None:
        reasoning_effort = "none"
    model_name = model or (profile["utility_model"] if utility else profile["model"])

    key = profile["api_key"] or config.require_api_key(profile["provider"])
    payload = _build_payload(profile, messages, model=model_name,
                             temperature=temperature, max_tokens=max_tokens,
                             reasoning_effort=reasoning_effort, stream=True)

    finish_reason = None
    produced = False

    with requests.post(_endpoint(profile), headers=_headers(key), json=payload,
                       stream=True, timeout=config.LLM_TIMEOUT) as resp:
        if resp.status_code >= 400:
            raise requests.HTTPError(
                f"{label} {resp.status_code}: {_error_detail(resp)}", response=resp)

        # SSE is UTF-8 by specification, but a server that sends
        # "Content-Type: text/event-stream" with no charset makes requests fall
        # back to ISO-8859-1 (per HTTP's old text/* default). Decoding the
        # stream with that turns every non-ASCII character into mojibake —
        # "—" arrives as "â€”", box-drawing characters as runs of "â" — even
        # though the bytes on the wire are perfectly good UTF-8. Trust the
        # spec over the header and decode the body as UTF-8 ourselves.
        resp.encoding = "utf-8"

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[len("data:"):].strip()
            if not data:
                continue
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            # Some providers report mid-stream failures in-band rather than
            # with a failing HTTP status.
            if chunk.get("error"):
                err = chunk["error"]
                msg = err.get("message") if isinstance(err, dict) else err
                raise RuntimeError(f"{label} error: {str(msg)[:500]}")
            choices = chunk.get("choices") or []
            if not choices:
                continue          # e.g. a trailing usage-only chunk
            choice = choices[0]
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                produced = True
                yield piece
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    reason = (finish_reason or "").lower()
    if meta is not None:
        meta.update({
            "provider": profile["provider"],
            "label": label,
            "model": model_name,
            "finish_reason": finish_reason,
            "truncated": reason in _TRUNCATED_REASONS,
            # A stream that ends without ANY terminal chunk never reported a
            # finish reason — the provider just closed the connection. Gemini's
            # OpenAI-compatible endpoint does this intermittently mid-word (seen
            # in practice: a 152-char reply that simply evaporated, then the
            # same prompt completed normally on the next attempt), and it is
            # indistinguishable from a clean stop to a caller that only counts
            # text deltas. Callers use this to tell "finished" from "died".
            "incomplete": produced and finish_reason is None,
            "blocked": (not produced) and reason in _BLOCKED_REASONS,
        })
    if not produced and reason in _BLOCKED_REASONS:
        raise RuntimeError(
            f"{label} blocked this response ({finish_reason}). Try rephrasing the "
            "prompt or switching model."
        )


def chat(messages: list[dict], *, temperature: float = 0.7,
         max_tokens: int | None = None, reasoning_effort: str | None = None,
         provider: str | None = None, model: str | None = None,
         utility: bool = False) -> str:
    """Non-streaming convenience wrapper (still uses the streaming endpoint
    under the hood — that's the one path proven to work reliably against
    every provider's API here)."""
    return "".join(stream_chat(messages, temperature=temperature,
                               max_tokens=max_tokens,
                               reasoning_effort=reasoning_effort,
                               provider=provider, model=model, utility=utility))


def test_key(key: str, *, provider: str | None = None,
             model: str | None = None) -> tuple[bool, str]:
    """Make one minimal request to confirm a key works for the selected
    provider and model, so Settings can give immediate feedback instead of
    the user finding out mid-generation."""
    profile = config.llm_profile(provider)
    label = profile["label"]
    model_name = model or profile["model"]
    # Always the content model, not the utility one: that's the model the
    # user is actually about to generate with.
    payload = _build_payload(profile, [{"role": "user", "content": "Hi"}],
                             model=model_name, temperature=0, max_tokens=32,
                             reasoning_effort=None, stream=False)
    try:
        resp = requests.post(_endpoint(profile), headers=_headers(key),
                             json=payload, timeout=_TEST_TIMEOUT)
    except requests.Timeout:
        return False, (
            f"{label} didn't answer within {_TEST_TIMEOUT[1]}s. Newer thinking "
            "models can be slow on a cold first call — try Test key again, or "
            "choose a faster model."
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    if resp.status_code >= 400:
        detail = _error_detail(resp)
        hint = ""
        if resp.status_code == 404:
            hint = (" The model name may have been retired — the message above "
                    "usually names a current one; paste that into Model.")
        return False, f"{label} rejected this key (HTTP {resp.status_code}): {detail}{hint}"
    return True, f"Key works ✓ ({label} · {model_name})"
