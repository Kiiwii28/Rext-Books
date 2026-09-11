// Default prompt templates (mirrors prompts.py) + selection -> mode mapping.
// The user can edit the text; the *mode* is fixed by what block is selected.

import { pathTo } from "./store.js";

export const TEMPLATES = {
  outline:
    'Please create an outline for a textbook on the topic of "{topic}" under {count} main headings.',
  subheadings:
    'Please create {count} subheadings for "{title}"{under} in a textbook on "{topic}".',
  content:
    'Please write the textbook content for the subsection "{title}"{under} in a textbook on "{topic}".',
};

export const COUNT_LABEL = {
  outline: "Number of headings",
  subheadings: "Number of subheadings",
  content: null,
};

export const TONES = ["Technical", "Academic", "Blog", "Conversational", "Informative", "Casual"];
export const DEPTHS = ["Beginner", "Intermediate", "Advanced"];

/** Given the selected node (or null), return { mode, targetId, node }.
 *  - nothing                 -> outline (whole book)
 *  - a heading selected      -> subheadings (targets that heading)
 *  - a subheading selected   -> content, or subheadings if `subOverride === "subheadings"`
 *  - a section selected      -> content (targets its parent subheading)
 *  `subOverride` lets the dock's Sub-topics/Content toggle steer a subheading.
 */
export function resolveMode(selectedId, subOverride) {
  if (!selectedId) return { mode: "outline", targetId: null, node: null };
  const chain = pathTo(selectedId);
  const node = chain[chain.length - 1];
  if (!node) return { mode: "outline", targetId: null, node: null };
  if (node.type === "heading") return { mode: "subheadings", targetId: node.id, node };
  if (node.type === "subheading") {
    const m = subOverride === "subheadings" ? "subheadings" : "content";
    return { mode: m, targetId: node.id, node };
  }
  if (node.type === "section") {
    const parent = chain[chain.length - 2];
    return { mode: "content", targetId: parent?.id ?? null, node: parent ?? null };
  }
  return { mode: "outline", targetId: null, node: null };
}

/** Does this subheading already contain nested sub-topics? */
export function hasSubTopics(node) {
  return !!(node?.children || []).some((c) => c.type === "subheading");
}

export function fillTemplate(mode, { topic, count, selectedId }) {
  const chain = selectedId ? pathTo(selectedId) : [];
  const last = chain[chain.length - 1];

  // Which node the generation is *about*, and everything above it in the tree.
  // For content on a section block, that's the parent subheading.
  let aboutIdx = chain.length - 1;
  if (mode === "content" && last?.type === "section") aboutIdx -= 1;
  const about = chain[aboutIdx] || null;
  const ancestors = chain
    .slice(0, Math.max(0, aboutIdx))
    .map((n) => (n.title || "").trim())
    .filter(Boolean);

  const title = (about?.title || "").trim();
  const crumbs = ancestors.map((t) => `"${t}"`).join(" › ");
  const under = crumbs ? ` (nested under ${crumbs})` : "";

  return TEMPLATES[mode]
    .replaceAll("{topic}", topic || "this topic")
    .replaceAll("{title}", title || "this section")
    .replaceAll("{under}", under)
    .replaceAll("{count}", count);
}

/** Parse a numbered/bulleted list from the model into clean title strings. */
export function parseList(text) {
  return text
    .split("\n")
    .map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim())
    .map((l) => l.replace(/\*\*/g, "").replace(/^#+\s*/, "").trim())
    .filter(Boolean);
}
