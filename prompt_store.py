"""Prompt text, loaded from data instead of being baked into code.

``prompts.defaults.json`` (repo root) is the **golden source of truth** for
every prompt string the app sends. The code in ``prompts.py`` / ``sparks.py`` /
``images.py`` only decides *which* strings to use and how to assemble them;
the words themselves come from here. When a prompt is fixed or improved, edit
the golden file — that is the change. Nothing else needs updating.

User tweaks live in ``prompts.local.json`` next to it, written by the Settings
→ Advanced panel. That file holds only the blocks the user changed; anything
missing falls back to the golden file. "Reset" simply deletes the override, so
a reset always reverts to whatever the golden file says *now* — never to a
frozen copy that would miss later prompt fixes.

Both files are read per call (the override file is mtime-cached), so an edit
made in the UI takes effect on the next generation with no restart. A change to
the golden file itself is a code change and needs a restart.
"""

from __future__ import annotations

import json
import re
import threading

from config import BASE_DIR

DEFAULTS_FILE = BASE_DIR / "prompts.defaults.json"
LOCAL_FILE = BASE_DIR / "prompts.local.json"

_lock = threading.Lock()
_overrides_cache: tuple[float, dict] | None = None

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load_defaults() -> dict:
    """The golden file, read once at import. A missing or malformed file is a
    developer error, not something to paper over: a silent fallback would mean
    the app is running prompts nobody can find."""
    try:
        data = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Prompt defaults file is missing: {DEFAULTS_FILE}. It is part of the "
            "app (see README) — restore it from the repository.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Prompt defaults file could not be read: {DEFAULTS_FILE}: {exc}") from exc
    blocks = data.get("blocks")
    if not isinstance(blocks, dict) or not blocks:
        raise RuntimeError(f"{DEFAULTS_FILE} has no 'blocks' object.")
    return blocks


_BLOCKS: dict[str, dict] = _load_defaults()


def _load_overrides() -> dict:
    global _overrides_cache
    try:
        mtime = LOCAL_FILE.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _overrides_cache and _overrides_cache[0] == mtime:
            return _overrides_cache[1]
        try:
            raw = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A hand-edited, broken override file must never take the app down:
            # fall back to the golden defaults until it is fixed or reset.
            return {}
        data = raw.get("blocks") if isinstance(raw, dict) else None
        overrides = {k: v for k, v in (data or {}).items()
                     if isinstance(k, str) and isinstance(v, str) and v.strip()}
        _overrides_cache = (mtime, overrides)
        return overrides


def get(key: str, **fmt) -> str:
    """The text for ``key``: user override if present, else the golden text.
    Pass format kwargs only for templates that contain placeholders."""
    text = _load_overrides().get(key)
    if text is None:
        block = _BLOCKS.get(key)
        if block is None:
            raise KeyError(f"unknown prompt block: {key!r}")
        text = block["text"]
    return text.format(**fmt) if fmt else text


def is_overridden(key: str) -> bool:
    return key in _load_overrides()


def blocks() -> list[dict]:
    """Everything the Advanced panel needs, in a stable order."""
    overrides = _load_overrides()
    out = []
    for key, block in _BLOCKS.items():
        override = overrides.get(key)
        out.append({
            "key": key,
            "group": block.get("group", "Other"),
            "label": block.get("label", key),
            "help": block.get("help", ""),
            "tier": block.get("tier", "safe"),
            "default": block["text"],
            "value": override if override is not None else block["text"],
            "modified": override is not None,
        })
    out.sort(key=lambda b: (b["group"], b["label"]))
    return out


def check_placeholders(key: str, text: str) -> list[str]:
    """Placeholders a replacement text dropped (or invented). Formatting a
    template with a missing {name} raises, so this is worth catching at save
    time rather than at generation time."""
    block = _BLOCKS.get(key)
    if block is None:
        return [f"unknown prompt block: {key}"]
    want = set(_PLACEHOLDER.findall(block["text"]))
    got = set(_PLACEHOLDER.findall(text))
    problems = []
    if want - got:
        problems.append("missing placeholder(s): " + ", ".join(sorted(want - got)))
    if got - want:
        problems.append("unknown placeholder(s): " + ", ".join(sorted(got - want)))
    return problems


def set_overrides(updates: dict[str, str]) -> list[str]:
    """Apply ``{key: text}``. An empty/blank text deletes the override (reset).
    Returns a list of validation warnings (saved anyway — the file is yours)."""
    unknown = [k for k in updates if k not in _BLOCKS]
    if unknown:
        raise KeyError("unknown prompt block(s): " + ", ".join(sorted(unknown)))
    warnings: list[str] = []
    overrides = dict(_load_overrides())
    for key, text in updates.items():
        text = (text or "").replace("\r\n", "\n")
        if not text.strip():
            overrides.pop(key, None)
            continue
        warnings += [f"{key}: {p}" for p in check_placeholders(key, text)]
        overrides[key] = text
    _write_overrides(overrides)
    return warnings


def reset(keys: list[str] | None = None) -> None:
    """Delete overrides for ``keys`` (or all of them when None)."""
    if keys is None:
        try:
            LOCAL_FILE.unlink()
        except FileNotFoundError:
            pass
        _invalidate()
        return
    overrides = dict(_load_overrides())
    for key in keys:
        overrides.pop(key, None)
    _write_overrides(overrides)


def _write_overrides(overrides: dict) -> None:
    payload = {"_note": "Local prompt overrides — reset from Settings → Advanced. "
                        "Blocks not listed here use prompts.defaults.json.",
               "blocks": dict(sorted(overrides.items()))}
    data = json.dumps(payload, indent=2, ensure_ascii=False)
    with _lock:
        tmp = LOCAL_FILE.with_suffix(".tmp")
        tmp.write_text(data + "\n", encoding="utf-8")
        tmp.replace(LOCAL_FILE)
    _invalidate()


def _invalidate() -> None:
    global _overrides_cache
    with _lock:
        _overrides_cache = None
