// Markdown formatting actions for a <textarea> — Bold/Italic/headings/lists/
// etc. Uses HTMLTextAreaElement.setRangeText rather than reassigning
// `.value`, so the browser's native undo/redo (Ctrl+Z) keeps working, same
// as if the user had typed the change themselves.

function fireInput(ta) {
  ta.dispatchEvent(new Event("input"));
  ta.focus();
}

/** Wrap the selection in `marker...marker` (bold/italic/strike/code) — click
 *  again on already-wrapped text to remove it instead of double-wrapping. */
function wrapSelection(ta, marker, placeholder) {
  const s = ta.selectionStart, e = ta.selectionEnd;
  const val = ta.value;
  const before = val.slice(Math.max(0, s - marker.length), s);
  const after = val.slice(e, e + marker.length);
  if (before === marker && after === marker) {
    const inner = val.slice(s, e);
    const os = s - marker.length;
    ta.setRangeText(inner, os, e + marker.length, "select");
    ta.selectionStart = os;
    ta.selectionEnd = os + inner.length;
  } else {
    const text = s !== e ? val.slice(s, e) : placeholder;
    ta.setRangeText(marker + text + marker, s, e, "select");
    ta.selectionStart = s + marker.length;
    ta.selectionEnd = ta.selectionStart + text.length;
  }
  fireInput(ta);
}

function lineRange(ta) {
  const s = ta.selectionStart, e = ta.selectionEnd;
  const val = ta.value;
  const lineStart = val.lastIndexOf("\n", s - 1) + 1;
  let lineEnd = val.indexOf("\n", e);
  if (lineEnd === -1) lineEnd = val.length;
  return { lineStart, lineEnd };
}

/** Apply `fn` to every line touched by the selection (headings/lists/quote —
 *  these prefix whole lines rather than wrapping arbitrary text). */
function transformLines(ta, fn) {
  const { lineStart, lineEnd } = lineRange(ta);
  const out = ta.value.slice(lineStart, lineEnd).split("\n").map(fn).join("\n");
  ta.setRangeText(out, lineStart, lineEnd, "select");
  ta.selectionStart = lineStart;
  ta.selectionEnd = lineStart + out.length;
  fireInput(ta);
}

const stripListMarkers = (line) => line.replace(/^[-*+]\s+/, "").replace(/^\d+\.\s+/, "").replace(/^>\s?/, "");

function toggleHeading(ta, level) {
  const marker = "#".repeat(level) + " ";
  transformLines(ta, (line) => {
    const m = line.match(/^(#{1,6})\s+(.*)$/);
    if (m && m[1].length === level) return m[2];   // same level again -> plain text
    return marker + (m ? m[2] : line);
  });
}

export function applyMarkdownAction(ta, action) {
  const ACTIONS = {
    h1: () => toggleHeading(ta, 1),
    h2: () => toggleHeading(ta, 2),
    h3: () => toggleHeading(ta, 3),
    h4: () => toggleHeading(ta, 4),
    h5: () => toggleHeading(ta, 5),
    h6: () => toggleHeading(ta, 6),
    bold: () => wrapSelection(ta, "**", "bold text"),
    italic: () => wrapSelection(ta, "_", "italic text"),
    strike: () => wrapSelection(ta, "~~", "strikethrough text"),
    code: () => wrapSelection(ta, "`", "code"),
    ul: () => transformLines(ta, (line) =>
      /^[-*+]\s+/.test(line) ? line.replace(/^[-*+]\s+/, "") : "- " + stripListMarkers(line)),
    ol: () => {
      let n = 1;
      transformLines(ta, (line) =>
        /^\d+\.\s+/.test(line) ? line.replace(/^\d+\.\s+/, "") : `${n++}. ` + stripListMarkers(line));
    },
    quote: () => transformLines(ta, (line) =>
      /^>\s?/.test(line) ? line.replace(/^>\s?/, "") : "> " + stripListMarkers(line)),
    link: () => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const text = ta.value.slice(s, e) || "link text";
      ta.setRangeText(`[${text}](url)`, s, e, "select");
      const urlStart = s + text.length + 3;   // "[" + text + "]("
      ta.selectionStart = urlStart;
      ta.selectionEnd = urlStart + 3;         // selects the "url" placeholder
      fireInput(ta);
    },
    codeblock: () => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const text = ta.value.slice(s, e) || "code";
      ta.setRangeText("\n```\n" + text + "\n```\n", s, e, "select");
      ta.selectionStart = s + 5;
      ta.selectionEnd = ta.selectionStart + text.length;
      fireInput(ta);
    },
    table: () => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      ta.setRangeText(
        "\n| Column 1 | Column 2 | Column 3 |\n| --- | --- | --- |\n" +
        "| Cell | Cell | Cell |\n| Cell | Cell | Cell |\n",
        s, e, "end",
      );
      fireInput(ta);
    },
    hr: () => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      ta.setRangeText("\n---\n", s, e, "end");
      fireInput(ta);
    },
  };
  ACTIONS[action]?.();
}
