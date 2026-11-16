"""Spark — cross-breed two nodes of a textbook into a new synthesised section.

The user picks exactly two blocks and one mode; each mode reframes how the two
are combined. ``store.sparkInsert`` parses the first ``# ``/``## `` line of the
output as the new node's title, so that heading line is a RULE here.
"""

from __future__ import annotations

import prompt_store
import prompts


def mode_specific(mode_key: str) -> str:
    """The mode's instruction paragraph (prompt text lives in the prompt store)."""
    return prompt_store.get(f"spark.mode.{mode_key}.specific")


def mode_template(mode_key: str) -> str:
    """The mode's default task template ('{a}' / '{b}' placeholders)."""
    return prompt_store.get(f"spark.mode.{mode_key}.template")


def _base(*, no_diagrams: bool = False, no_images: bool = False) -> str:
    """Built per-request, not baked in at import time — so an explicit "no
    diagrams" / "no images" ask (from the user's standing preference or their
    per-request prompt) can drop the matching RULE+DEFAULT pair entirely,
    rather than leaving a DEFAULT that plainly tells the model to add one
    right next to an instruction telling it not to. See prompts.py's
    ``_content_system_prompt`` for the same treatment on regular content
    generation."""
    rules = [prompt_store.get(k) for k in (
        "spark.rules.title", "spark.rules.markdown_only",
        "spark.rules.list_format", "spark.rules.synthesise")]
    rules.append(prompt_store.get(
        "spark.rules.diagram.off" if no_diagrams else "spark.rules.diagram.on"))
    rules.append(prompt_store.get(
        "spark.rules.image.off" if no_images else "spark.rules.image.on"))

    defaults = [prompt_store.get("spark.defaults.structure")]
    if not no_diagrams:
        defaults.append(prompt_store.get("spark.defaults.diagram"))
        defaults.append(prompt_store.get("spark.defaults.diagram_size"))
    defaults.append(prompt_store.get("spark.defaults.focused"))

    return prompts._frame(
        prompt_store.get("spark.intro"),
        rules=rules, defaults=defaults,
    )


SPARK_MODES: dict[str, dict[str, str]] = {
    "cross-pollinate": {
        "label": "Cross-Pollinate",
        "blurb": "Synthesise the two topics — shared connections, transferred frameworks, hidden patterns.",
    },
    "unified-theory": {
        "label": "Unified Theory",
        "blurb": "Find the hidden principle(s) that unify both topics.",
    },
    "contrarian": {
        "label": "Contrarian",
        "blurb": "Devil's advocate — challenge the assumptions, expose hidden costs and risks.",
    },
    "socratic": {
        "label": "Socratic Questioning",
        "blurb": "Generate probing questions at the intersection — no answers.",
    },
    "temporal": {
        "label": "Temporal Dimension",
        "blurb": "Past → Present → Future treatment of the intersection.",
    },
    "scale": {
        "label": "Scale Shifting",
        "blurb": "Micro (individual) vs macro (systemic) views of the intersection.",
    },
    "metaphor": {
        "label": "Metaphor Mapping",
        "blurb": "Explain the link via 3 metaphors from unrelated domains.",
    },
    "missing-node": {
        "label": "Missing Node Detection",
        "blurb": "Find the bridging concept that should exist between them — then write it.",
    },
    "what-if": {
        "label": "What If?",
        "blurb": "Counterfactual scenarios at the intersection, then explore the best one.",
    },
    "connections-map": {
        "label": "Connections Map",
        "blurb": "Enumerate the links, rate their strength, flag the unexpected ones.",
    },
}


def default_prompt(mode_key: str, a_title: str, b_title: str) -> str:
    if mode_key not in SPARK_MODES:
        return prompt_store.get("spark.fallback_template").format(
            a=a_title, b=b_title)
    return mode_template(mode_key).format(a=a_title or "A", b=b_title or "B")


def modes_summary() -> dict[str, dict[str, str]]:
    return {k: {"label": v["label"], "blurb": v["blurb"],
                "template": mode_template(k)}
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
    parts = [base + "\n\nMODE:\n" + mode_specific(mode_key).strip()]

    style = prompts.style_line(tone, depth)
    if style:
        parts.append(style)
    if overarching:
        parts.append(
            prompt_store.get("shared.standing_preference_wrapper") + overarching
        )
    if prompts._EM_DASH_RE.search(combined_hint):
        parts.append(prompt_store.get("shared.no_em_dash"))
    parts.append(prompts.override_note())

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
