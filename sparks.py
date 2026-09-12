"""Spark — cross-breed two nodes of a textbook into a new synthesised section.

The user picks exactly two blocks and one mode; each mode reframes how the two
are combined. ``store.sparkInsert`` parses the first ``# ``/``## `` line of the
output as the new node's title, so that heading line is a RULE here.
"""

from __future__ import annotations

import prompts


def _base(*, no_diagrams: bool = False, no_images: bool = False) -> str:
    """Built per-request, not baked in at import time — so an explicit "no
    diagrams" / "no images" ask (from the user's standing preference or their
    per-request prompt) can drop the matching RULE+DEFAULT pair entirely,
    rather than leaving a DEFAULT that plainly tells the model to add one
    right next to an instruction telling it not to. See prompts.py's
    ``_content_system_prompt`` for the same treatment on regular content
    generation."""
    rules = [
        'Start with a single "# " title line (it becomes the new section title), '
        "then the body.",
        "Output Markdown only: no preamble, no meta-commentary, no code fence around "
        "the whole answer.",
        "Genuinely synthesise the two sources — do not just summarise each in turn.",
    ]
    rules.append(
        "The user does not want any diagrams in this response — do not emit a "
        "Mermaid code block or any other diagram, full stop."
        if no_diagrams else
        "Every diagram must be a valid Mermaid fenced code block ('mermaid') with "
        "plain-text labels."
    )
    rules.append(
        "The user does not want any images in this response — do not emit a "
        "Markdown image link, full stop."
        if no_images else
        "Only use a Markdown image link for a real, stable URL you are confident "
        "exists. Never use a placeholder-image service and never invent a URL — use a "
        "Mermaid diagram or a sentence instead."
    )

    defaults = [
        "Structure the body with '##'/'###' subheadings, use concrete examples, and "
        "end with a short 'Takeaway'.",
    ]
    if not no_diagrams:
        defaults.append(
            "Include about one small Mermaid diagram where it clarifies the synthesis. "
            "If the user asks for more, comply — up to about four."
        )
        defaults.append(
            "Keep each Mermaid diagram page-sized: at most ~10 nodes, short labels, and "
            "left-to-right ('LR') flow for any long chain so it stays wide, not tall."
        )
    defaults.append("Keep it a focused section.")

    return prompts._frame(
        "You are a thought-synthesis engine for a recursive textbook. You take two "
        "pieces of source material and produce ONE original, self-contained section "
        "that genuinely combines them.",
        rules=rules, defaults=defaults,
    )


SPARK_MODES: dict[str, dict[str, str]] = {
    "cross-pollinate": {
        "label": "Cross-Pollinate",
        "blurb": "Synthesise the two topics — shared connections, transferred frameworks, hidden patterns.",
        "specific": (
            "Synthesise A and B: identify genuine connections between them, apply a "
            "framework or method from one to the other, and surface the hidden pattern "
            "they share. Aim for a genuinely novel intersection."
        ),
        "template": 'Cross-pollinate "{a}" and "{b}" into one synthesised section.',
    },
    "unified-theory": {
        "label": "Unified Theory",
        "blurb": "Find the hidden principle(s) that unify both topics.",
        "specific": (
            "Identify the deep unifying principle(s) that connect A and B despite their "
            "surface differences. Reveal the shared underlying structure and show how "
            "both are instances of it."
        ),
        "template": 'What underlying principle unifies "{a}" and "{b}"? Reveal it.',
    },
    "contrarian": {
        "label": "Contrarian",
        "blurb": "Devil's advocate — challenge the assumptions, expose hidden costs and risks.",
        "specific": (
            "Argue the devil's-advocate position about A, using B as a lens. Challenge "
            "the standard assumptions, expose hidden costs, fragilities and risks, and "
            "make the strongest possible opposing case — rigorously, not glibly."
        ),
        "template": 'Make the contrarian case against the conventional view of "{a}", drawing on "{b}".',
    },
    "socratic": {
        "label": "Socratic Questioning",
        "blurb": "Generate probing questions at the intersection — no answers.",
        "specific": (
            "Produce a structured set of probing Socratic questions at the intersection "
            "of A and B — questions that expose hidden assumptions, force definitions, "
            "and provoke deeper thinking. Group them under '##' themes. Override the "
            "DEFAULTS for this mode: do NOT answer or explain, no worked examples, and "
            "no Takeaway."
        ),
        "template": 'Ask the hard questions that live at the intersection of "{a}" and "{b}".',
    },
    "temporal": {
        "label": "Temporal Dimension",
        "blurb": "Past → Present → Future treatment of the intersection.",
        "specific": (
            "Treat the intersection of A and B across time, with three '##' sections: "
            "Past (origins, key figures, evolution), Present (current state, tools, "
            "examples), Future (trends, predictions, wild cards)."
        ),
        "template": 'Trace "{a}" × "{b}" through past, present and future.',
    },
    "scale": {
        "label": "Scale Shifting",
        "blurb": "Micro (individual) vs macro (systemic) views of the intersection.",
        "specific": (
            "Examine the intersection of A and B at two scales: the micro / individual "
            "level and the macro / systemic level. Show how the same phenomenon looks "
            "and behaves differently at each, and what emerges only at scale."
        ),
        "template": 'Zoom in and out on "{a}" × "{b}" — micro and macro.',
    },
    "metaphor": {
        "label": "Metaphor Mapping",
        "blurb": "Explain the link via 3 metaphors from unrelated domains.",
        "specific": (
            "Explain the relationship between A and B through exactly three vivid, "
            "extended metaphors, each drawn from a different unrelated domain (e.g. "
            "biology, architecture, music, cooking, geology). Develop each metaphor "
            "and note where it breaks down."
        ),
        "template": 'Explain how "{a}" relates to "{b}" using three metaphors from unrelated fields.',
    },
    "missing-node": {
        "label": "Missing Node Detection",
        "blurb": "Find the bridging concept that should exist between them — then write it.",
        "specific": (
            "First, in one short paragraph, identify precisely what is MISSING between A "
            "and B — the bridging concept, comparison, or section that should exist but "
            "doesn't. Then write that bridging section in full."
        ),
        "template": 'What concept is missing between "{a}" and "{b}"? Name it, then write it.',
    },
    "what-if": {
        "label": "What If?",
        "blurb": "Counterfactual scenarios at the intersection, then explore the best one.",
        "specific": (
            "Generate 4-6 sharp 'What if…' counterfactual scenarios at the intersection "
            "of A and B (list them under a '## Scenarios' heading), then pick the most "
            "revealing one and explore its consequences in depth."
        ),
        "template": 'Generate "what if" scenarios where "{a}" meets "{b}", then dig into the most interesting.',
    },
    "connections-map": {
        "label": "Connections Map",
        "blurb": "Enumerate the links, rate their strength, flag the unexpected ones.",
        "specific": (
            "Map the connections between A and B: enumerate the concrete links as a "
            "list, rate each link's strength (strong / moderate / weak / speculative), "
            "and call out the connections that are unexpected or usually overlooked. "
            "Override the DEFAULTS for this mode: no Takeaway."
        ),
        "template": 'Map every connection between "{a}" and "{b}" and rate how strong each is.',
    },
}


def default_prompt(mode_key: str, a_title: str, b_title: str) -> str:
    m = SPARK_MODES.get(mode_key)
    if not m:
        return f'Combine "{a_title}" and "{b_title}".'
    return m["template"].format(a=a_title or "A", b=b_title or "B")


def modes_summary() -> dict[str, dict[str, str]]:
    return {k: {"label": v["label"], "blurb": v["blurb"], "template": v["template"]}
            for k, v in SPARK_MODES.items()}


def build_spark_messages(mode_key: str, user_prompt: str, a_text: str, b_text: str,
                         *, a_title: str = "A", b_title: str = "B",
                         tone: str | None = None, depth: str | None = None,
                         overarching: str | None = None) -> list[dict]:
    m = SPARK_MODES.get(mode_key)
    if not m:
        raise ValueError(f"unknown spark mode: {mode_key!r}")

    overarching = (overarching or "").strip()
    combined_hint = f"{overarching}\n{user_prompt or ''}"
    base = _base(
        no_diagrams=bool(prompts._NO_DIAGRAMS_RE.search(combined_hint)),
        no_images=bool(prompts._NO_IMAGES_RE.search(combined_hint)),
    )
    parts = [base + "\n\nMODE:\n" + m["specific"].strip()]

    style = [h for h in (prompts._TONE_HINT.get(tone or ""),
                         prompts._DEPTH_HINT.get(depth or "")) if h]
    if style:
        parts.append("STYLE (a DEFAULT — the user may override): " + " ".join(style))
    if overarching:
        parts.append(
            "USER'S STANDING PREFERENCE for this book — apply it throughout this "
            "response, even where it means skipping something a DEFAULT above "
            "suggested (RULES still win if there's a genuine conflict): " + overarching
        )
    if prompts._EM_DASH_RE.search(combined_hint):
        parts.append(
            "STRICT STYLE CHECK: the user does not want em-dashes (—) anywhere in this "
            "response. Use a comma, colon, period, or parentheses instead. Before "
            "finishing, mentally scan your draft for the — character and rephrase any "
            "sentence that has one."
        )
    parts.append(prompts.OVERRIDE_NOTE)

    source = (
        f"SOURCE A — {a_title}\n\n{a_text.strip()}\n\n"
        f"==========\n\n"
        f"SOURCE B — {b_title}\n\n{b_text.strip()}"
    )
    return [
        {"role": "system", "content": "\n\n".join(parts)},
        {"role": "user", "content": source},
        {"role": "user", "content": user_prompt.strip()},
    ]
