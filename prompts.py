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

_TONE_HINT = {
    "Technical": "Write in a precise technical register with correct terminology and concrete detail.",
    "Academic": "Write in a formal academic register with careful definitions and measured claims.",
    "Blog": "Write in an engaging blog style: direct address, short paragraphs, a lively voice.",
    "Conversational": "Write in a warm conversational voice, as if explaining to a colleague.",
    "Informative": "Write in a clear, neutral, informative voice.",
    "Casual": "Write in a relaxed, plain-spoken voice with everyday language.",
}
_DEPTH_HINT = {
    "Beginner": "Assume no prior knowledge; define terms and keep examples simple.",
    "Intermediate": "Assume some background; move at a steady pace with practical examples.",
    "Advanced": "Assume a strong background; go deep, use nuance, skip the basics.",
}

# Always the final instruction in the system prompt. Also reused by sparks.py.
OVERRIDE_NOTE = (
    "PRECEDENCE: If an instruction in the request conflicts with a RULE, follow the "
    "RULE and silently ignore only that part of the request. Everything a RULE does "
    "not cover — length, depth, structure, how many images or diagrams, whether to "
    "include a summary or examples, wording and emphasis — is a DEFAULT, and the "
    "user's instructions override it. When the user explicitly asks for more (or "
    "fewer) images or diagrams, honour that within the stated maximums."
)


def _frame(intro: str, *, rules: list[str], defaults: list[str]) -> str:
    return (
        intro.strip() + "\n\n"
        + "RULES (always follow):\n"
        + "\n".join(f"- {r}" for r in rules) + "\n\n"
        + "DEFAULTS (follow unless the user's instructions ask otherwise):\n"
        + "\n".join(f"- {d}" for d in defaults)
    )


_LIST_RULES = [
    'Output ONLY the list: one item per line, each line prefixed with a number and a period ("1. ").',
    "No preamble, no commentary, no blank lines, no headings, no other Markdown.",
    "Each line is a short title (a noun phrase), never a sentence or a description.",
]

SYSTEM_PROMPTS = {
    "outline": _frame(
        "You are a curriculum designer producing the top-level outline of a textbook.",
        rules=_LIST_RULES + [
            "Produce top-level chapter headings only — no sub-topics and no body text.",
        ],
        defaults=[
            "Produce roughly the number of headings the user asks for.",
            "Order them as a sensible teaching progression.",
            "Keep each title concise — about three to eight words.",
        ],
    ),
    "subheadings": _frame(
        "You are a curriculum designer breaking one part of a textbook into its subheadings.",
        rules=_LIST_RULES + [
            "Break down only the one node named in the request. Do not write body text "
            "and do not invent sibling chapters.",
        ],
        defaults=[
            "Produce roughly the number of subheadings the user asks for.",
            "Order them logically for teaching.",
            "Keep each title concise.",
        ],
    ),
}


def _content_system_prompt(*, no_diagrams: bool = False, no_images: bool = False,
                           use_images: bool = False) -> str:
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
    rules = [
        "Cover only the subsection named in the request — do not write sibling "
        "subsections or re-teach the parent chapter.",
        "Output Markdown only: no preamble, no meta-commentary, and do not wrap the "
        "whole answer in a code fence.",
        'Do not use a top-level "# " heading — the subsection heading is supplied by '
        'the app. Use "##" and deeper for internal structure.',
    ]
    rules.append(
        "The user does not want any diagrams in this response — do not emit a "
        "Mermaid code block or any other diagram, full stop."
        if no_diagrams else
        "Every diagram must be a valid Mermaid fenced code block (info string "
        "'mermaid') with plain-text labels."
    )
    if no_images:
        rules.append(
            "The user does not want any images in this response — do not emit a "
            "Markdown image link, full stop."
        )
    elif use_images:
        rules.append(
            "You have no way to know a real image URL, so NEVER write a Markdown "
            'image tag ("![...](...)") yourself and never invent or guess a URL. '
            "When a real photo or illustration would genuinely help, request one "
            "with a fenced ```image-search block instead — the app searches for "
            "and inserts a real image server-side after you finish. Format exactly:\n"
            "```image-search\n"
            "query: <specific search terms describing what the image should show>\n"
            "caption: <a short caption describing exactly what it depicts>\n"
            "```\n"
            "in place of an image tag, on its own line. If the app can't find a "
            "match, the request is silently dropped — so this never breaks the "
            "response either way."
        )
    else:
        rules.append(
            "Only use a Markdown image link for an image you can point to a real, stable "
            "URL for (e.g. a specific Wikimedia Commons file). NEVER use a placeholder-"
            "image service (placehold.co, dummyimage.com, via.placeholder.com, "
            "picsum.photos and the like) and never invent or guess an image URL. If you "
            "want to convey a figure you have no real URL for, draw it as a Mermaid "
            "diagram or describe it in a sentence instead — do not emit an image tag."
        )

    defaults = [
        'Open with a short orienting paragraph and close with a brief "Summary".',
        "Use worked examples where they aid understanding.",
    ]
    if not no_diagrams:
        defaults.append(
            "Include about one Mermaid diagram where a process, hierarchy, flow, "
            "sequence or timeline genuinely clarifies things. If the user asks for "
            "more diagrams, comply — up to about six."
        )
        defaults.append(
            "Keep each Mermaid diagram compact enough to fit on one page: at most ~10 "
            "nodes, short labels, and for a long chain or sequence use a left-to-right "
            "flow ('flowchart LR' / 'graph LR') rather than top-down so it stays wide, "
            "not tall. Split a big process into two smaller diagrams instead of one huge "
            "one."
        )
    if not no_images:
        defaults.append(
            "Use images sparingly — about one where it truly adds value. If the user "
            "asks for more images, comply — up to about eight."
        )
        if use_images:
            defaults.append(
                "Keep each image-search query SHORT — 2 to 4 keywords, like typing "
                'into an image search engine (e.g. "neuron diagram", "mitochondria '
                'structure", "eiffel tower"), never a full sentence or long '
                "descriptive phrase — those return far fewer/worse matches. Put all "
                "the specific detail in the caption instead (e.g. \"Diagram of a "
                'neuron labelling the dendrites, cell body, and axon") — it doubles '
                "as the alt text and as the yardstick used to judge which of the "
                "real search results actually matches; a vague caption like \"a "
                'neuron" makes that judgment far less reliable too.'
            )
    defaults.append("Keep it a focused subsection, not an exhaustive treatise.")

    return _frame(
        "You are an expert textbook author writing the body text for ONE subsection.",
        rules=rules, defaults=defaults,
    )

DEFAULT_TEMPLATES = {
    "outline": (
        'Please create an outline for a textbook on the topic of "{topic}" '
        "under {count} main headings."
    ),
    "subheadings": (
        'Please create {count} subheadings for "{title}"{under} in a textbook on "{topic}".'
    ),
    "content": (
        'Please write the textbook content for the subsection "{title}"{under} '
        'in a textbook on "{topic}".'
    ),
}


def _under_clause(ancestors: list[str] | None) -> str:
    """`` (nested under "A" › "B")`` for the chain of titles above this node."""
    crumbs = " › ".join(f'"{a.strip()}"' for a in (ancestors or []) if a and a.strip())
    return f" (nested under {crumbs})" if crumbs else ""


_REFINE_RULES = (
    "REVISION RULE: a draft of this subsection is given below. Return the COMPLETE "
    "revised Markdown and nothing else. Change what the user asks for and leave "
    "everything else — including image tags and Mermaid blocks — intact."
)

_CONTEXT_PREAMBLE = (
    "Below is related material the user picked from elsewhere in the same textbook. "
    "Use it only as background — for consistent terminology, to avoid repeating what "
    "it already covers, and to cross-reference where natural. Do NOT copy it, and "
    "stay within the scope of your assigned task.\n\n"
)


def build_messages(mode: str, user_prompt: str, *, tone: str | None = None,
                   depth: str | None = None, refine_source: str | None = None,
                   context_blocks: list[str] | None = None,
                   overarching: str | None = None,
                   use_images: bool = False) -> list[dict]:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode!r}")

    overarching = (overarching or "").strip()
    combined_hint = f"{overarching}\n{user_prompt or ''}"

    if mode == "content":
        system_prompt = _content_system_prompt(
            no_diagrams=bool(_NO_DIAGRAMS_RE.search(combined_hint)),
            no_images=bool(_NO_IMAGES_RE.search(combined_hint)),
            use_images=use_images,
        )
    else:
        system_prompt = SYSTEM_PROMPTS[mode]
    parts = [system_prompt]

    style = [h for h in (_TONE_HINT.get(tone or ""), _DEPTH_HINT.get(depth or "")) if h]
    if style:
        parts.append("STYLE (a DEFAULT — the user may override): " + " ".join(style))
    if overarching:
        # A standing preference the user set once for this book (e.g. "don't use
        # em-dashes") so they don't have to repeat it in every prompt. Same
        # precedence as STYLE: a DEFAULT, not a RULE — but phrased as a direct
        # instruction to follow even where it means skipping something a
        # DEFAULT above suggested, since a quiet "the user's instructions win"
        # precedence note elsewhere in the prompt is easy for the model to
        # under-weight against a concrete, specific DEFAULT bullet.
        parts.append(
            "USER'S STANDING PREFERENCE for this book — apply it throughout this "
            "response, even where it means skipping something a DEFAULT above "
            "suggested (RULES still win if there's a genuine conflict): "
            + overarching
        )
    if _EM_DASH_RE.search(combined_hint):
        parts.append(
            "STRICT STYLE CHECK: the user does not want em-dashes (—) anywhere in this "
            "response. Use a comma, colon, period, or parentheses instead. Before "
            "finishing, mentally scan your draft for the — character and rephrase any "
            "sentence that has one."
        )
    if mode == "content" and refine_source is not None:
        parts.append(_REFINE_RULES)
    parts.append(OVERRIDE_NOTE)

    messages = [{"role": "system", "content": "\n\n".join(parts)}]
    if context_blocks:
        joined = "\n\n----------\n\n".join(b.strip() for b in context_blocks if b.strip())
        if joined:
            messages.append({"role": "user", "content": _CONTEXT_PREAMBLE + joined})
    if mode == "content" and refine_source is not None:
        messages.append({"role": "user",
                         "content": "Current draft:\n\n" + refine_source.strip()})
    messages.append({"role": "user", "content": user_prompt.strip()})
    return messages


def default_prompt(mode: str, *, topic: str = "", title: str = "",
                   ancestors: list[str] | None = None, count: int = 3) -> str:
    return DEFAULT_TEMPLATES[mode].format(
        topic=topic or "this topic",
        title=title or "this section",
        under=_under_clause(ancestors),
        count=count,
    )
