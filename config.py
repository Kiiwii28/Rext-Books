"""Configuration and secret loading for Rextbooks.

Generation is provider-agnostic: every supported model is reached through an
OpenAI-compatible Chat Completions endpoint, described by a preset in
``PROVIDERS`` below and consumed by the single client in ``llm.py``.

The API key for the selected provider can come from (in priority order):
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

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
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

# --------------------------------------------------------------------------- #
#  LLM providers                                                              #
# --------------------------------------------------------------------------- #
#
# One HTTP client (llm.py), several profiles. Everything below speaks the same
# OpenAI-compatible Chat Completions wire format, so "supporting" a provider
# means adding a preset here — not new client code — and switching between
# them is just changing which preset is active.
#
# A preset is also where each provider's *behavioural* differences live, as
# data rather than scattered `if provider == ...` branches:
#
#   supports_reasoning_effort
#       DeepSeek accepts ``reasoning_effort``; ``"none"`` skips its hidden
#       reasoning pass entirely, which is why the short internal calls in
#       images.py ask for it (without it, a ``max_tokens=50`` judge call can
#       spend its whole budget thinking and return nothing). Gemini's
#       OpenAI-compatible layer has no equivalent switch, so the same intent
#       is expressed through ``utility_model`` instead: a non-thinking model
#       for those short calls, so there is no thinking pass to starve.
#
#   utility_model
#       The cheap model for short internal calls (image judging, search-query
#       rewriting). ``None`` = use the content model and cheapen it with
#       ``reasoning_effort`` instead.
#
#   context_chars
#       How much picked "extra context" / Spark source material may be sent.
#       Sized to the model's real input window — switching to a smaller-
#       context model without this would fail on any book with a sizeable
#       outline, which is exactly the kind of breakage a provider swap should
#       not cause.
#
# Resolution order for the active provider is: the Settings choice, then
# ``LLM_PROVIDER``, then the default — the same "UI beats env" precedence API
# keys already use, so switching in the UI is never silently overridden by a
# stale shell variable.

DEFAULT_PROVIDER = "deepseek"

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash"],
        "utility_model": None,
        "context_chars": 400000,          # v4 has a 1M-token window
        "supports_reasoning_effort": True,
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "key_placeholder": "sk-…",
        "keys_url": "https://platform.deepseek.com/api_keys",
    },
    "gemini": {
        "label": "Google Gemini",
        # Gemini's OpenAI-compatible layer — same wire format as the rest, so
        # llm.py needs nothing Gemini-specific to talk to it.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        # Retired names are a live hazard here: Google answers a 404 for an
        # old model ("This model ... is no longer available to new users")
        # rather than silently aliasing it, so these defaults must be current.
        # The field is free text, and a 404 from Test key names the suggested
        # replacement in its message — that's the fastest way to catch a
        # future retirement without a code change.
        "default_model": "gemini-3.8-flash",
        # Suggestions for the Settings model dropdown (a free-text field with a
        # datalist, so anything a provider accepts can still be typed). Kept
        # newest-first; the default is one of them. Add a name here whenever
        # Google ships (or the user wants to toggle to) another one.
        "models": [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
        # No separate cheap model: the older non-thinking Flash models are the
        # ones that get retired first (2.0/2.5 are already gone for new keys),
        # so utility calls reuse the content model and rely on llm.py's raised
        # visible-output floor instead of a reasoning_effort switch this
        # provider doesn't have.
        "utility_model": None,
        "context_chars": 400000,          # ~1M-token input window
        "supports_reasoning_effort": False,
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "base_url_env": "GEMINI_BASE_URL",
        "key_placeholder": "AIza…",
        "keys_url": "https://aistudio.google.com/apikey",
    },
}

# Accepted spellings for ``LLM_PROVIDER`` / a Settings payload, so a natural
# "google" doesn't silently fall back to DeepSeek.
_PROVIDER_ALIASES = {"google": "gemini", "google-gemini": "gemini"}


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _preset(name: str | None) -> dict:
    """A provider's preset. Never raises — an unknown name falls back to the
    default, so a typo in an env var or a stale saved setting can't make the
    app unbootable. Takes an already-resolved name (it never calls
    ``get_llm_provider``) so callers may use it while holding the lock."""
    key = _clean(name).lower()
    key = _PROVIDER_ALIASES.get(key, key) or DEFAULT_PROVIDER
    return PROVIDERS.get(key) or PROVIDERS[DEFAULT_PROVIDER]


BOOKS_DIR = Path(os.getenv("BOOKS_DIR", BASE_DIR / "books"))
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

# Network timeouts (seconds) for one LLM call: (connect, read). The read
# timeout is per-chunk, not for the whole generation, so a long section is
# fine as long as the stream keeps flowing.
LLM_TIMEOUT = (10, 300)

# Wall-clock ceiling (seconds) for one headless-Chrome PDF/EPUB-render pass.
# The browser's own --virtual-time-budget flag (how long the page gets to
# settle before printing) is separate and much shorter — this is just "how
# long are we willing to wait for the subprocess to finish and hand back a
# file" once printing/DOM-dumping is actually underway. A large, image- and
# diagram-heavy book can genuinely take minutes, not seconds. Env-overridable
# for anyone whose books need longer still.
PDF_RENDER_TIMEOUT = int(os.getenv("REXTBOOKS_PDF_TIMEOUT", "300"))


# --------------------------------------------------------------------------- #
#  Key bundles ("master keys")                                                 #
# --------------------------------------------------------------------------- #
#
# One short passcode that fills in several provider keys at once — for a
# non-technical user who shouldn't have to paste a Gemini key, a DeepSeek key
# and a Pexels key separately.
#
# The bundles themselves are *configuration you own*, never something the app
# writes or a browser can read:
#
#   1. the environment variable ``REXTBOOKS_KEY_BUNDLES`` holding JSON (this is
#      the one to use on Render, where the container's disk is wiped), or
#   2. ``key_bundles.json`` next to the app (gitignored) for local use.
#
# Shape — each top-level key is the passcode the user types:
#
#   {
#     "rk-mum-8f3a91c2d5e64b70a1c9": {
#       "label": "Mum",
#       "provider": "gemini",              # optional; inferred from the keys
#       "model": "gemini-3.5-flash-lite",  # optional — pins exactly one model
#       "models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
#                                          # optional — the ONLY models allowed
#       "excludeModels": ["gemini-3.8-flash"],
#                                          # optional — models that are NOT allowed
#       "keys": {
#         "gemini": "AIza…",
#         "deepseek": "sk-…",
#         "pexels": "…"
#       }
#     }
#   }
#
# (``{"label": …, "gemini": "…"}`` with the keys at the top level also works.)
#
# **Every model field is optional, and leaving all of them out means every model
# is allowed.** There are two ways to restrict, and either can be omitted:
#
#   ``excludeModels``  the models that are NOT allowed ("everything except
#                      these"), measured against the provider's own preset list.
#                      This is the usual "plan" wording: block the expensive one.
#   ``models``         the only models allowed ("just these"), when the list of
#                      good ones is shorter than the list of bad ones.
#   ``model``          the strictest shortcut: exactly one model, no choice.
#
# Each of them applies to the bundle's own provider, or can be spelled
# ``{"gemini": [...], "deepseek": [...]}`` to differ per provider. If both
# ``models`` and ``excludeModels`` are given, ``models`` is the starting set and
# the exclusions are removed from it. A model that is not allowed is refused by
# the server, not merely hidden in the UI.
#
# A passcode is a *credential*: anyone holding it spends the keys inside it.
# Use a long random one (the README shows a one-liner to generate them), never
# anything guessable.
#
# Resolution is per request and per browser, never global: unlocking stores only
# an opaque bundle id in the user's signed session cookie, so two people on the
# same hosted instance each keep their own bundle. Nothing is written to
# ``local_settings.json``, so one person unlocking cannot change another's setup,
# and a redeploy cannot forget a bundle (the env var comes back with the image).

BUNDLES_ENV = "REXTBOOKS_KEY_BUNDLES"
_BUNDLES_FILE = BASE_DIR / "key_bundles.json"
_BUNDLE_KEY_NAMES = ("deepseek", "gemini", "pexels")
_BUNDLE_LLM_KEYS = ("gemini", "deepseek")   # order = "which provider wins" when unspecified

_bundle_cache: tuple[object, dict] | None = None
_bundles_warned = False
_ctx = threading.local()   # per-request active bundle id


def _bundle_id(passcode: str) -> str:
    """An opaque id for a passcode — the passcode itself is never stored in the
    session cookie or written anywhere."""
    return hashlib.sha256(("rextbooks:" + passcode).encode("utf-8")).hexdigest()[:16]


def _clean_model_list(value: object) -> list[str]:
    """A de-duplicated list of non-empty model names (order preserved)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        name = _clean(item)
        if name and name not in out:
            out.append(name)
    return out[:20]


def _parse_model_map(raw: object, provider: str) -> dict[str, list[str]]:
    """A bundle's ``models`` / ``excludeModels`` field.

    Either a plain list (meaning the bundle's own provider) or a mapping of
    provider → list. An empty result means "not specified", which is always a
    legal state: no list of either kind means nothing is restricted."""
    if isinstance(raw, dict):
        out: dict[str, list[str]] = {}
        for name, value in raw.items():
            key = _clean(name).lower()
            key = _PROVIDER_ALIASES.get(key, key)
            models = _clean_model_list(value)
            if key in PROVIDERS and models:
                out[key] = models
        return out
    models = _clean_model_list(raw)
    return {provider: models} if models else {}


def _parse_bundles(raw: object) -> dict[str, dict]:
    """Normalise the configured JSON into
    ``{id: {id, label, provider, model, models, keys}}``.

    Anything malformed is skipped rather than raising — a typo in an env var
    must not stop the app booting for someone who isn't using bundles at all."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for passcode, entry in raw.items():
        if not isinstance(passcode, str) or len(passcode) < 8 or not isinstance(entry, dict):
            continue
        keys: dict[str, str] = {}
        nested = entry.get("keys")
        for k in _BUNDLE_KEY_NAMES:
            value = None
            if isinstance(nested, dict):
                value = nested.get(k)
            if not isinstance(value, str) or not value.strip():
                value = entry.get(k)          # flat shorthand
            if isinstance(value, str) and value.strip():
                keys[k] = value.strip()
        if not any(keys.get(k) for k in _BUNDLE_LLM_KEYS):
            continue                          # no LLM key = nothing usable
        provider = _clean(entry.get("provider")).lower()
        provider = _PROVIDER_ALIASES.get(provider, provider)
        if provider not in PROVIDERS:
            provider = next((p for p in _BUNDLE_LLM_KEYS if keys.get(p)), DEFAULT_PROVIDER)
        allowed = _parse_model_map(entry.get("models"), provider)
        excluded = _parse_model_map(entry.get("excludeModels"), provider)
        model = _clean(entry.get("model"))
        if model and provider not in allowed:
            # A pinned model is simply a one-item allow-list, so both spellings
            # go through the same checks further down.
            allowed[provider] = [model]
        out[_bundle_id(passcode)] = {
            "id": _bundle_id(passcode),
            "label": _clean(entry.get("label")) or "Key bundle",
            "provider": provider,
            "model": model,
            "models": allowed,
            "excludeModels": excluded,
            "keys": keys,
        }
    return out


def _bundles() -> dict[str, dict]:
    """Configured bundles, re-read when ``key_bundles.json`` changes."""
    global _bundle_cache, _bundles_warned
    try:
        mtime: object = _BUNDLES_FILE.stat().st_mtime
    except OSError:
        mtime = None
    if _bundle_cache is not None and _bundle_cache[0] == mtime:
        return _bundle_cache[1]

    merged: dict = {}
    if mtime is not None:
        try:
            loaded = json.loads(_BUNDLES_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                merged.update(loaded)
        except (OSError, json.JSONDecodeError) as exc:
            if not _bundles_warned:
                print(f"[config] ignoring {_BUNDLES_FILE.name}: {exc}", file=sys.stderr)
                _bundles_warned = True
    env_raw = _clean(os.getenv(BUNDLES_ENV))
    if env_raw:
        try:
            loaded = json.loads(env_raw)
            if isinstance(loaded, dict):
                merged.update(loaded)
        except json.JSONDecodeError as exc:
            if not _bundles_warned:
                print(f"[config] {BUNDLES_ENV} is not valid JSON: {exc}", file=sys.stderr)
                _bundles_warned = True

    _bundle_cache = (mtime, _parse_bundles(merged))
    return _bundle_cache[1]


def bundles_configured() -> bool:
    return bool(_bundles())


def resolve_passcode(passcode: str) -> dict | None:
    """The bundle a typed passcode unlocks, or None. Compared against every
    configured bundle (no early exit) with a constant-time check."""
    passcode = _clean(passcode)
    if not passcode:
        return None
    target = _bundle_id(passcode)
    found: dict | None = None
    for bundle_id, bundle in _bundles().items():
        if hmac.compare_digest(bundle_id, target):
            found = bundle
    return found


def set_active_bundle(bundle_id: str | None) -> None:
    """Pin this request/thread to one bundle (called from the Flask hook that
    reads the user's session). Unknown or absent id = no bundle."""
    _ctx.bundle = bundle_id if bundle_id in _bundles() else None
    _ctx.provider = None
    _ctx.models = None


def set_request_provider(provider: str | None) -> None:
    """The provider this request's user has picked *within* their bundle.

    Kept per request/session rather than in ``local_settings.json``: two people
    sharing a bundle on one instance must be able to use different providers at
    the same time without overwriting each other."""
    _ctx.provider = _clean(provider).lower() or None


def set_request_models(models: object) -> None:
    """The models this request's user has picked *within* their bundle, as
    ``{provider: model}``. Session state for the same reason as the provider:
    one browser's model choice never rewrites the shared settings file."""
    if isinstance(models, dict):
        clean = {str(k): _clean(v) for k, v in models.items() if _clean(v)}
        _ctx.models = clean or None
    else:
        _ctx.models = None


def request_models() -> dict[str, str]:
    """The per-session model choices, for ``app.py`` to persist in the cookie."""
    return dict(getattr(_ctx, "models", None) or {})


def bundle_allowed_models(provider: str | None = None) -> list[str]:
    """The models the unlocked bundle permits for ``provider`` — empty when the
    bundle places no limit at all.

    ``excludeModels`` is the usual "plan" spelling ("everything except these"),
    so it is measured against the provider's own preset list; ``models`` narrows
    further when both are given. A configuration that excludes *every* preset
    model is treated as a typo and falls back to the provider's default model
    rather than silently allowing everything."""
    bundle = get_active_bundle()
    if bundle is None:
        return []
    name = _normalize(provider or get_llm_provider())
    allow = list(bundle["models"].get(name) or [])
    deny = bundle["excludeModels"].get(name) or []
    if allow:
        kept = [m for m in allow if m not in deny]
        return kept or allow          # never let a stray exclusion open it up
    if deny:
        preset_models = list(_preset(name)["models"])
        if not preset_models:
            return []
        kept = [m for m in preset_models if m not in deny]
        return kept or [preset_models[0]]
    return []


def bundle_providers() -> list[str]:
    """Providers the unlocked bundle can actually serve, best first."""
    bundle = get_active_bundle()
    if bundle is None:
        return []
    return [p for p in _BUNDLE_LLM_KEYS if bundle["keys"].get(p)]


def get_active_bundle() -> dict | None:
    bundle_id = getattr(_ctx, "bundle", None)
    return _bundles().get(bundle_id) if bundle_id else None


def clear_active_bundle() -> None:
    _ctx.bundle = None
    _ctx.provider = None
    _ctx.models = None


def key_bundle_info() -> dict:
    """Browser-safe view for the Settings dialog — labels and which providers
    are covered, never a key or a passcode."""
    bundle = get_active_bundle()
    if bundle is None:
        return {"configured": bool(_bundles()), "unlocked": False, "providers": [],
                "models": {}, "excludeModels": {}}
    available = bundle_providers()
    return {
        "configured": True,
        "unlocked": True,
        "label": bundle["label"],
        "providers": [k for k in _BUNDLE_KEY_NAMES if bundle["keys"].get(k)],
        # Which LLM providers this bundle can serve — the user may switch between
        # all of them (when there's more than one) without touching shared config.
        "availableProviders": available,
        "provider": get_llm_provider(),
        "model": bundle["model"],
        # provider -> the models this bundle actually permits (absent/empty means
        # unrestricted). ``excludeModels`` is reported alongside it so the UI can
        # say *why* a model is missing rather than just showing a shorter list.
        "models": {p: ms for p in _BUNDLE_LLM_KEYS if (ms := bundle_allowed_models(p))},
        "excludeModels": {p: list(m) for p, m in bundle["excludeModels"].items() if m},
        # The pinned model belongs to the bundle's default provider, so the UI
        # can stay quiet about it once the user has switched to another one.
        "modelProvider": bundle["provider"] if bundle["model"] else "",
    }


# --------------------------------------------------------------------------- #
#  API key                                                                     #
# --------------------------------------------------------------------------- #

_SETTINGS_FILE = BASE_DIR / "local_settings.json"
_lock = threading.Lock()


def get_secret_key() -> str:
    """Key for signing the session cookie (which holds only an opaque bundle
    id). Comes from ``REXTBOOKS_SECRET_KEY`` when set — recommended on a hosted
    instance, so every deploy and instance signs alike — otherwise a random
    value generated once and kept in ``local_settings.json``."""
    env = _clean(os.getenv("REXTBOOKS_SECRET_KEY"))
    if env:
        return env
    with _lock:
        data = _read_settings()
        key = _clean(data.get("sessionSecret"))
        if not key:
            key = secrets.token_hex(32)
            data["sessionSecret"] = key
            _write_settings(data)
        return key


def _read_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_settings(data: dict) -> None:
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_FILE)


def _settings_snapshot() -> dict:
    with _lock:
        return _read_settings()


# --------------------------------------------------------------------------- #
#  Active provider / model                                                    #
# --------------------------------------------------------------------------- #
#
# Resolved per call rather than once at import: switching provider in
# ⚙ Settings has to take effect on the very next generation, with no restart.

def _normalize(name: str | None) -> str:
    key = _clean(name).lower()
    key = _PROVIDER_ALIASES.get(key, key)
    return key if key in PROVIDERS else DEFAULT_PROVIDER


def get_llm_provider() -> str:
    """The provider in effect: an unlocked key bundle's chosen provider (the
    user may pick any provider the bundle has a key for), then the Settings
    choice, then ``LLM_PROVIDER``, then the default."""
    bundle = get_active_bundle()
    if bundle is not None:
        available = bundle_providers()
        preferred = getattr(_ctx, "provider", None)
        if preferred in available:
            return preferred
        if bundle["provider"] in available:
            return bundle["provider"]
        if available:
            return available[0]
    saved = _clean(_settings_snapshot().get("llmProvider")).lower()
    saved = _PROVIDER_ALIASES.get(saved, saved)
    if saved in PROVIDERS:
        return saved
    env = _clean(os.getenv("LLM_PROVIDER")).lower()
    env = _PROVIDER_ALIASES.get(env, env)
    if env in PROVIDERS:
        return env
    return DEFAULT_PROVIDER


def set_llm_provider(name: str) -> str:
    key = _PROVIDER_ALIASES.get(_clean(name).lower(), _clean(name).lower())
    if key not in PROVIDERS:
        raise ValueError(
            f"unknown provider {name!r}; expected one of {', '.join(PROVIDERS)}"
        )
    bundle = get_active_bundle()
    if bundle is not None:
        # Switching inside a bundle is allowed for any provider it holds a key
        # for — it only changes this session's choice, never the shared file.
        available = bundle_providers()
        if key not in available:
            labels = ", ".join(PROVIDERS[p]["label"] for p in available) or "none"
            raise RuntimeError(
                f"The unlocked key bundle ({bundle['label']}) has no "
                f"{PROVIDERS[key]['label']} key — it can use: {labels}."
            )
        set_request_provider(key)
        return key
    with _lock:
        data = _read_settings()
        data["llmProvider"] = key
        _write_settings(data)
    return key


def get_llm_model(provider: str | None = None) -> str:
    """The model for ``provider`` (default: the active one).

    An unlocked key bundle that lists models is a hard limit, not a default: the
    user's choice (kept in their session) if it's on the list, otherwise the
    bundle's pinned model, otherwise the first allowed one. Without such a list
    it falls back to: session choice, pinned model, saved setting, the
    provider's own env var, a generic ``LLM_MODEL``, then the preset default."""
    name = _normalize(provider or get_llm_provider())
    preset = _preset(name)
    bundle = get_active_bundle()
    if bundle is not None:
        chosen = (getattr(_ctx, "models", None) or {}).get(name)
        allowed = bundle_allowed_models(name)
        if allowed:
            if chosen in allowed:
                return chosen
            if bundle["model"] and name == bundle["provider"]:
                return bundle["model"]
            return allowed[0]
        if bundle["model"] and name == bundle["provider"]:
            return bundle["model"]
        if chosen:
            return chosen
    saved = _clean((_settings_snapshot().get("llmModels") or {}).get(name))
    if saved:
        return saved
    env = _clean(os.getenv(preset["model_env"]))
    if env:
        return env
    # LLM_MODEL is a convenience for whichever provider is active; it must
    # not leak onto a second provider the user has also configured.
    if name == get_llm_provider():
        generic = _clean(os.getenv("LLM_MODEL"))
        if generic:
            return generic
    return preset["default_model"]


def set_llm_model(model: str, provider: str | None = None) -> None:
    """Choose the model for one provider; an empty string clears the choice so
    the default applies again.

    Inside a key bundle the choice is stored in this browser's session (never in
    the shared settings file), and a bundle that restricts models only accepts
    one of them — the check is here, so it holds even if the UI is bypassed."""
    name = _normalize(provider or get_llm_provider())
    preset = _preset(name)
    model = _clean(model)
    bundle = get_active_bundle()
    if bundle is not None:
        allowed = bundle_allowed_models(name)
        if allowed:
            if not model:
                model = allowed[0]
            if model not in allowed:
                raise RuntimeError(
                    f"The unlocked key bundle ({bundle['label']}) is limited to: "
                    f"{', '.join(allowed)}."
                )
        elif bundle["model"] and name == bundle["provider"]:
            raise RuntimeError(
                f"The unlocked key bundle ({bundle['label']}) fixes this model — "
                "lock it first to choose a different one."
            )
        models = dict(getattr(_ctx, "models", None) or {})
        if model:
            models[name] = model
        else:
            models.pop(name, None)
        _ctx.models = models or None
        return
    with _lock:
        data = _read_settings()
        models = dict(data.get("llmModels") or {})
        if model and model != preset["default_model"]:
            models[name] = model
        else:
            models.pop(name, None)
        if models:
            data["llmModels"] = models
        else:
            data.pop("llmModels", None)
        _write_settings(data)


def get_llm_base_url(provider: str | None = None) -> str:
    name = _normalize(provider or get_llm_provider())
    preset = _preset(name)
    env = _clean(os.getenv(preset["base_url_env"]))
    if not env and name == get_llm_provider():
        env = _clean(os.getenv("LLM_BASE_URL"))
    return (env or preset["base_url"]).rstrip("/")


def get_llm_utility_model(provider: str | None = None) -> str:
    """The model for short internal calls — a preset's non-thinking model
    where one exists, otherwise the content model."""
    name = _normalize(provider or get_llm_provider())
    return _preset(name)["utility_model"] or get_llm_model(name)


def supports_reasoning_effort(provider: str | None = None) -> bool:
    return bool(_preset(_normalize(provider or get_llm_provider()))["supports_reasoning_effort"])


def get_context_char_budget(provider: str | None = None) -> int:
    """Characters of picked extra context allowed for this provider.
    ``REXTBOOKS_CONTEXT_CHARS`` overrides it for the active provider."""
    name = _normalize(provider or get_llm_provider())
    if name == get_llm_provider():
        env = _clean(os.getenv("REXTBOOKS_CONTEXT_CHARS"))
        if env.isdigit():
            return int(env)
    return int(_preset(name)["context_chars"])


# --------------------------------------------------------------------------- #
#  API key (one per provider, so switching never strands the other key)       #
# --------------------------------------------------------------------------- #

def _settings_key(provider: str) -> str:
    data = _settings_snapshot()
    key = _clean((data.get("providerKeys") or {}).get(provider))
    if not key and provider == "deepseek":
        # Before providers were selectable there was exactly one key field.
        key = _clean(data.get("deepseekApiKey"))
    return key


def get_api_key(provider: str | None = None) -> str:
    """The key actually in effect for ``provider``: an unlocked key bundle,
    then one saved in Settings, otherwise its .env / environment value (or a
    generic ``LLM_API_KEY`` for the active provider)."""
    name = _normalize(provider or get_llm_provider())
    bundle = get_active_bundle()
    if bundle is not None and bundle["keys"].get(name):
        return bundle["keys"][name]
    key = _settings_key(name)
    if key:
        return key
    key = _clean(os.getenv(_preset(name)["api_key_env"]))
    if key:
        return key
    if name == get_llm_provider():
        return _clean(os.getenv("LLM_API_KEY"))
    return ""


def api_key_source(provider: str | None = None) -> str:
    """Where the provider's active key (if any) came from: "bundle",
    "settings", "env", or "none"."""
    name = _normalize(provider or get_llm_provider())
    bundle = get_active_bundle()
    if bundle is not None and bundle["keys"].get(name):
        return "bundle"
    if _settings_key(name):
        return "settings"
    if _clean(os.getenv(_preset(name)["api_key_env"])):
        return "env"
    if name == get_llm_provider() and _clean(os.getenv("LLM_API_KEY")):
        return "env"
    return "none"


def set_api_key(key: str, provider: str | None = None) -> None:
    """Save a key for one provider, or clear it (empty string) to fall back
    to that provider's .env / environment value.

    Refused while an unlocked key bundle supplies that provider: writing here
    would change the shared settings file for everyone else on the instance."""
    name = _normalize(provider or get_llm_provider())
    bundle = get_active_bundle()
    if bundle is not None and bundle["keys"].get(name):
        raise RuntimeError(
            f"The {_preset(name)['label']} key is supplied by the unlocked key "
            "bundle — lock it first to edit keys here."
        )
    with _lock:
        data = _read_settings()
        keys = dict(data.get("providerKeys") or {})
        legacy = _clean(data.pop("deepseekApiKey", ""))   # migrate the old single-key field
        if legacy and not keys.get("deepseek"):
            keys["deepseek"] = legacy
        key = _clean(key)
        if key:
            keys[name] = key
        else:
            keys.pop(name, None)
        if keys:
            data["providerKeys"] = keys
        else:
            data.pop("providerKeys", None)
        _write_settings(data)


def require_api_key(provider: str | None = None) -> str:
    name = _normalize(provider or get_llm_provider())
    key = get_api_key(name)
    if not key:
        preset = _preset(name)
        raise RuntimeError(
            f"No {preset['label']} API key configured yet. Add one in ⚙ Settings "
            f"({preset['label']} → API key), or set {preset['api_key_env']} in .env, "
            "to start generating."
        )
    return key


# --------------------------------------------------------------------------- #
#  Resolved profile / browser-safe status                                     #
# --------------------------------------------------------------------------- #
#
# ``llm_profile`` is server-side only (it includes the key) and is what
# llm.py reads for each request. ``llm_status`` is the browser-safe view:
# it says whether a key exists, never what it is.

def llm_profile(provider: str | None = None) -> dict:
    name = _normalize(provider or get_llm_provider())
    preset = _preset(name)
    return {
        "provider": name,
        "label": preset["label"],
        "base_url": get_llm_base_url(name),
        "model": get_llm_model(name),
        "utility_model": get_llm_utility_model(name),
        "api_key": get_api_key(name),
        "api_key_env": preset["api_key_env"],
        "supports_reasoning_effort": bool(preset["supports_reasoning_effort"]),
        "context_chars": get_context_char_budget(name),
    }


def llm_status(provider: str | None = None) -> dict:
    name = _normalize(provider or get_llm_provider())
    preset = _preset(name)
    allowed = bundle_allowed_models(name)
    return {
        "provider": name,
        "label": preset["label"],
        "model": get_llm_model(name),
        "defaultModel": preset["default_model"],
        # A key bundle that names its models replaces the preset list entirely,
        # so the Settings dialog can't offer anything the server would refuse.
        "models": allowed or list(preset["models"]),
        "allowedModels": allowed,          # [] = no restriction
        "modelLocked": len(allowed) == 1,  # only one choice: nothing to pick
        "contextChars": get_context_char_budget(name),
        "hasApiKey": bool(get_api_key(name)),
        "keySource": api_key_source(name),
        "keyPlaceholder": preset["key_placeholder"],
        "keysUrl": preset["keys_url"],
    }


def llm_providers() -> list[dict]:
    """Every supported provider with its own (browser-safe) status, so the
    Settings dialog can show which ones already have a key."""
    return [llm_status(name) for name in PROVIDERS]


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
#  Blurb (the "A textbook on <topic>." line on export cover pages/TOC notes)   #
# --------------------------------------------------------------------------- #

DEFAULT_BLURB_TEMPLATE = "A textbook on {topic}."


def get_blurb_template() -> str:
    with _lock:
        return (_read_settings().get("blurbTemplate") or "").strip() or DEFAULT_BLURB_TEMPLATE


def set_blurb_template(template: str) -> None:
    with _lock:
        data = _read_settings()
        template = (template or "").strip()
        if template and template != DEFAULT_BLURB_TEMPLATE:
            data["blurbTemplate"] = template
        else:
            data.pop("blurbTemplate", None)
        _write_settings(data)


def format_blurb(topic: str) -> str:
    """The formatted blurb line for one book. Falls back to the default
    template if the user's saved one has a typo'd/unknown placeholder —
    a broken Settings value should never be able to break an export."""
    tmpl = get_blurb_template()
    try:
        return tmpl.format(topic=topic or "")
    except (KeyError, IndexError, ValueError):
        return DEFAULT_BLURB_TEMPLATE.format(topic=topic or "")


# --------------------------------------------------------------------------- #
#  Custom export palettes (user-created in the Export dialog; global, not     #
#  per-book, so a palette made once is available to every book)               #
# --------------------------------------------------------------------------- #

def get_custom_palettes() -> dict:
    with _lock:
        return dict(_read_settings().get("customPalettes") or {})


def save_custom_palette(key: str, palette: dict) -> None:
    with _lock:
        data = _read_settings()
        customs = dict(data.get("customPalettes") or {})
        customs[key] = palette
        data["customPalettes"] = customs
        _write_settings(data)


def delete_custom_palette(key: str) -> bool:
    with _lock:
        data = _read_settings()
        customs = dict(data.get("customPalettes") or {})
        if key not in customs:
            return False
        del customs[key]
        if customs:
            data["customPalettes"] = customs
        else:
            data.pop("customPalettes", None)
        _write_settings(data)
        return True


# --------------------------------------------------------------------------- #
#  Pexels API key (optional — powers the image-search tab's stock-photo       #
#  fallback; Wikimedia Commons search works with no key at all)               #
# --------------------------------------------------------------------------- #
#
# STUB: get a free key at https://www.pexels.com/api/ and paste it into
# ⚙ Settings, or set PEXELS_API_KEY in a local .env file. Same precedence as
# the provider keys above (Settings-UI value wins over .env/env) — but a single
# key for all providers, since Pexels isn't an LLM.

_ENV_PEXELS_KEY = os.getenv("PEXELS_API_KEY", "").strip()


def get_pexels_key() -> str:
    bundle = get_active_bundle()
    if bundle is not None and bundle["keys"].get("pexels"):
        return bundle["keys"]["pexels"]
    with _lock:
        ui_key = (_read_settings().get("pexelsApiKey") or "").strip()
    return ui_key or _ENV_PEXELS_KEY


def set_pexels_key(key: str) -> None:
    bundle = get_active_bundle()
    if bundle is not None and bundle["keys"].get("pexels"):
        raise RuntimeError(
            "The Pexels key is supplied by the unlocked key bundle — lock it "
            "first to edit keys here."
        )
    with _lock:
        data = _read_settings()
        key = (key or "").strip()
        if key:
            data["pexelsApiKey"] = key
        else:
            data.pop("pexelsApiKey", None)
        _write_settings(data)


# Pexels has no usage dashboard on their own site — the only place quota is
# ever visible is the X-Ratelimit-* response headers on each API call, so
# images.py records them here (persisted, not just in-memory) every time it
# actually calls Pexels, and Settings displays the last-known snapshot.
def get_pexels_usage() -> dict:
    with _lock:
        return _read_settings().get("pexelsUsage") or {}


def set_pexels_usage(limit: int | None, remaining: int | None, reset: int | None) -> None:
    with _lock:
        data = _read_settings()
        data["pexelsUsage"] = {
            "limit": limit, "remaining": remaining, "reset": reset,
            "checkedAt": time.time(),
        }
        _write_settings(data)
