"""Prompt construction for the three generation modes.

The *mode* is decided by which block the user selected, not by the user's prompt
text; the response handler in ``app.py`` only ever creates the node type for that
mode, so the prompt cannot make the app build the wrong thing.

Each system prompt is split into two parts:

  RULES     — invariants the app depends on (parseable output, scope, no stray
              top-level headings). Always enforced.
  DEFAULTS  — house style (length, structure, how many images / diagrams).
              The user's editable prompt overrides these.

  outline      -> a flat numbered list of main headings
  subheadings  -> a flat numbered list of subheadings for one node
  content      -> Markdown body for one subsection (a "section")
"""

from __future__ import annotations

import re

import prompt_store

MODES = ("outline", "subheadings", "content")

# Best-effort detectors for a handful of common, concrete asks that would
# otherwise directly contradict one of the fixed DEFAULTS below (e.g. our own
# "include about one Mermaid diagram" default vs. a user who explicitly wants
# none). Matched against the user's standing preference + their per-request
# prompt combined. Deliberately narrow/loose regexes, not a general intent
# parser — false negatives just fall back to normal (weaker) prompt-based
# compliance; false positives are unlikely given how specific the phrasing is.
_NO_DIAGRAMS_RE = re.compile(
    r"\b(?:no|don'?t|never|avoid|without|skip)\b[^.\n]{0,20}\bdiagrams?\b", re.I)
_NO_IMAGES_RE = re.compile(
    r"\b(?:no|don'?t|never|avoid|without|skip)\b[^.\n]{0,20}\bimages?\b", re.I)
_EM_DASH_RE = re.compile(r"em[\s-]?dash", re.I)

TONES = ("Technical", "Academic", "Blog", "Conversational", "Informative", "Casual")
DEPTHS = ("Beginner", "Intermediate", "Advanced")

# Tone/depth hints are text, so they live in prompts.defaults.json (golden) and
# can be overridden per user — these maps are only the id lookup.
_TONE_KEYS = {
    "Technical": "tone.technical",
    "Academic": "tone.academic",
    "Blog": "tone.blog",
    "Conversational": "tone.conversational",
    "Informative": "tone.informative",
    "Casual": "tone.casual",
}
_DEPTH_KEYS = {
    "Beginner": "depth.beginner",
    "Intermediate": "depth.intermediate",
    "Advanced": "depth.advanced",
}


def tone_hint(tone: str | None) -> str:
    key = _TONE_KEYS.get(tone or "")
    return prompt_store.get(key) if key else ""


def depth_hint(depth: str | None) -> str:
    key = _DEPTH_KEYS.get(depth or "")
    return prompt_store.get(key) if key else ""


def style_line(tone: str | None, depth: str | None) -> str:
    """The full 'STYLE (a DEFAULT …): …' line, or '' when neither is set."""
    hints = [h for h in (tone_hint(tone), depth_hint(depth)) if h]
    if not hints:
        return ""
    return prompt_store.get("shared.style_wrapper") + " ".join(hints)


def override_note() -> str:
    """Always the final instruction in the system prompt. Also used by sparks.py."""
    return prompt_store.get("shared.precedence")


def continuation_prompt() -> str:
    """Final user turn when a reply was cut off (see app.py)."""
    return prompt_store.get("shared.continuation")


def _frame(intro: str, *, rules: list[str], defaults: list[str]) -> str:
    return (
        intro.strip() + "\n\n"
        + prompt_store.get("shared.frame.rules_header") + "\n"
        + "\n".join(f"- {r}" for r in rules) + "\n\n"
        + prompt_store.get("shared.frame.defaults_header") + "\n"
        + "\n".join(f"- {d}" for d in defaults)
    )


def _list_rules() -> list[str]:
    return [prompt_store.get(k) for k in (
        "list.rules.output_only", "list.rules.no_preamble", "list.rules.short_titles")]


def _list_system_prompt(mode: str) -> str:
    """Outline / subheadings system prompt, built fresh so prompt edits apply
    to the very next generation without a restart."""
    rules = _list_rules()
    if mode == "outline":
        return _frame(
            prompt_store.get("outline.intro"),
            rules=rules + [prompt_store.get("outline.rules.headings_only")],
            defaults=[prompt_store.get(k) for k in (
                "outline.defaults.count", "outline.defaults.order", "outline.defaults.length")],
        )
    return _frame(
        prompt_store.get("subheadings.intro"),
        rules=rules + [prompt_store.get("subheadings.rules.scope")],
        defaults=[prompt_store.get(k) for k in (
            "subheadings.defaults.count", "subheadings.defaults.order",
            "subheadings.defaults.length")],
    )


FREQUENCIES = ("Low", "Medium", "High")


def _frequency_key(prefix: str, value: str) -> str:
    """Block id for a Low/Medium/High setting, defaulting to Medium for an
    unexpected value rather than raising deep inside prompt assembly."""
    level = (value or "").strip().lower()
    return f"{prefix}.{level if level in ('low', 'medium', 'high') else 'medium'}"


def _content_system_prompt(*, no_diagrams: bool = False, no_images: bool = False,
                           use_images: bool = False, image_frequency: str = "Medium",
                           diagram_frequency: str = "Medium", length: str = "Medium",
                           summary_section: bool = True, terminology_section: bool = False) -> str:
    """Built per-request (not baked into SYSTEM_PROMPTS) so that an explicit "no
    diagrams" / "no images" ask can drop the matching RULE+DEFAULT pair entirely,
    instead of leaving a DEFAULT that plainly tells the model to add one right
    next to a user instruction telling it not to — a direct contradiction inside
    the same system prompt that a "the user's instructions win" precedence note
    alone doesn't reliably resolve.

    ``use_images`` (the book's "Use images" toggle, off by default) switches the
    image RULE from "never invent a URL, describe it instead" — the only safe
    option when the model truly has no way to get a real one — to a fenced
    ```image-search request block the app resolves server-side via a real
    Wikimedia/Pexels search after generation finishes (images.py). Ignored
    entirely when ``no_images`` is set — an explicit "don't use images" always
    wins over the book-level toggle."""
    use_images = use_images and not no_images
    rules = [prompt_store.get(k) for k in (
        "content.rules.scope", "content.rules.markdown_only",
        "content.rules.no_h1", "content.rules.list_format")]
    rules.append(prompt_store.get(
        "content.rules.diagram.off" if no_diagrams else "content.rules.diagram.on"))
    if no_images:
        rules.append(prompt_store.get("content.rules.image.none"))
    elif use_images:
        rules.append(prompt_store.get("content.rules.image.search"))
    else:
        rules.append(prompt_store.get("content.rules.image.plain"))

    defaults = [prompt_store.get("content.defaults.opening")]
    if length != "Low":
        # Worked examples add length on their own — skip suggesting them when
        # the length preference is fighting to stay brief; otherwise the two
        # DEFAULTS pull in opposite directions and brevity tends to lose.
        defaults.append(prompt_store.get("content.defaults.examples"))
    if summary_section:
        defaults.append(prompt_store.get("content.defaults.summary"))
    else:
        # A plain omission isn't enough here — closing with a "Summary" is
        # such a strong, common textbook convention that the model adds one
        # unprompted even with no instruction either way (confirmed: turning
        # this off while saying nothing further still produced a Summary
        # section). Needs an explicit negative, the same as no_diagrams/
        # no_images above.
        defaults.append(prompt_store.get("content.defaults.no_summary"))
    if terminology_section:
        defaults.append(prompt_store.get("content.defaults.terminology"))
    else:
        defaults.append(prompt_store.get("content.defaults.no_terminology"))
    if not no_diagrams:
        defaults.append(prompt_store.get(
            _frequency_key("content.defaults.diagram_frequency", diagram_frequency)))
        defaults.append(prompt_store.get("content.defaults.diagram_compact"))
    if not no_images:
        defaults.append(prompt_store.get(
            _frequency_key("content.defaults.image_frequency", image_frequency)))
        if use_images:
            defaults.append(prompt_store.get("content.defaults.image_query_short"))
            defaults.append(prompt_store.get("content.defaults.image_caption"))
    defaults.append(prompt_store.get(
        _frequency_key("content.defaults.length", length)))

    return _frame(prompt_store.get("content.intro"), rules=rules, defaults=defaults)

def _under_clause(ancestors: list[str] | None) -> str:
    """`` (nested under "A" › "B")`` for the chain of titles above this node."""
    crumbs = " › ".join(f'"{a.strip()}"' for a in (ancestors or []) if a and a.strip())
    return f" (nested under {crumbs})" if crumbs else ""


def build_messages(mode: str, user_prompt: str, *, tone: str | None = None,
                   depth: str | None = None, refine_source: str | None = None,
                   context_blocks: list[str] | None = None,
                   book_outline: str | None = None,
                   overarching: str | None = None,
                   use_images: bool = False,
                   image_frequency: str = "Medium", diagram_frequency: str = "Medium",
                   length: str = "Medium", summary_section: bool = True,
                   terminology_section: bool = False) -> list[dict]:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode!r}")

    overarching = (overarching or "").strip()
    combined_hint = f"{overarching}\n{user_prompt or ''}"

    if mode == "content":
        system_prompt = _content_system_prompt(
            no_diagrams=bool(_NO_DIAGRAMS_RE.search(combined_hint)),
            no_images=bool(_NO_IMAGES_RE.search(combined_hint)),
            use_images=use_images,
            image_frequency=image_frequency if image_frequency in FREQUENCIES else "Medium",
            diagram_frequency=diagram_frequency if diagram_frequency in FREQUENCIES else "Medium",
            length=length if length in FREQUENCIES else "Medium",
            summary_section=summary_section,
            terminology_section=terminology_section,
        )
    else:
        system_prompt = _list_system_prompt(mode)
    parts = [system_prompt]

    style = style_line(tone, depth)
    if style:
        parts.append(style)
    if overarching:
        # A standing preference the user set once for this book (e.g. "don't use
        # em-dashes") so they don't have to repeat it in every prompt. Same
        # precedence as STYLE: a DEFAULT, not a RULE — but phrased as a direct
        # instruction to follow even where it means skipping something a
        # DEFAULT above suggested, since a quiet "the user's instructions win"
        # precedence note elsewhere in the prompt is easy for the model to
        # under-weight against a concrete, specific DEFAULT bullet.
        parts.append(
            prompt_store.get("shared.standing_preference_wrapper") + overarching
        )
    if _EM_DASH_RE.search(combined_hint):
        parts.append(prompt_store.get("shared.no_em_dash"))
    if mode == "content" and refine_source is not None:
        parts.append(prompt_store.get("common.refine_rule"))
    parts.append(override_note())

    messages = [{"role": "system", "content": "\n\n".join(parts)}]
    if book_outline and book_outline.strip():
        messages.append({"role": "user", "content": prompt_store.get(
            "common.outline_preamble") + "\n\n" + book_outline.strip()})
    if context_blocks:
        joined = "\n\n----------\n\n".join(b.strip() for b in context_blocks if b.strip())
        if joined:
            messages.append({"role": "user", "content": prompt_store.get(
                "common.context_preamble") + "\n\n" + joined})
    if mode == "content" and refine_source is not None:
        messages.append({"role": "user",
                         "content": "Current draft:\n\n" + refine_source.strip()})
    messages.append({"role": "user", "content": user_prompt.strip()})
    return messages


def default_prompt(mode: str, *, topic: str = "", title: str = "",
                   ancestors: list[str] | None = None, count: int = 3) -> str:
    return prompt_store.get(f"template.{mode}").format(
        topic=topic or "this topic",
        title=title or "this section",
        under=_under_clause(ancestors),
        count=count,
    )
