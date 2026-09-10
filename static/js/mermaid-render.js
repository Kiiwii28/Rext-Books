// Render <pre class="mermaid"> blocks to SVG, themed to match the app.
// Mermaid is loaded lazily from a CDN the first time a diagram appears.

const MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/+esm";

let mermaid = null;
let loading = null;
let idc = 0;
const svgCache = new Map();   // diagram source -> rendered SVG (or null on error)

function themeVars() {
  const s = getComputedStyle(document.documentElement);
  const g = (name, fallback) => (s.getPropertyValue(name).trim() || fallback);
  const ink = g("--ink", "#2b2a28");
  const soft = g("--ink-soft", "#6b6a66");
  const accent = g("--accent", "#4b3f8f");
  return {
    fontFamily: '"Inter", -apple-system, "Segoe UI", system-ui, sans-serif',
    fontSize: "13px",
    primaryColor: accent + "1f",
    primaryTextColor: ink,
    primaryBorderColor: accent,
    secondaryColor: accent + "12",
    tertiaryColor: "#ffffff00",
    lineColor: accent,
    textColor: ink,
    mainBkg: accent + "1f",
    nodeBorder: accent,
    clusterBkg: accent + "0d",
    clusterBorder: accent + "55",
    titleColor: ink,
    edgeLabelBackground: g("--bg", "#f4f4f2"),
    labelBoxBorderColor: accent,
    actorBorder: accent,
    actorBkg: accent + "1f",
    noteBkgColor: accent + "14",
    noteBorderColor: accent + "55",
  };
}

async function ensureMermaid() {
  if (mermaid) return mermaid;
  if (!loading) {
    loading = import(MERMAID_URL)
      .then((m) => {
        mermaid = m.default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: themeVars(),
          flowchart: { curve: "basis", useMaxWidth: true, rankSpacing: 34, nodeSpacing: 26, padding: 6 },
          sequence: { useMaxWidth: true },
          mindmap: { padding: 8 },
        });
        return mermaid;
      })
      .catch(() => { mermaid = null; });
  }
  await loading;
  return mermaid;
}

// keep a tall diagram from dominating a section — cap its height, scale to fit
function fitSvg(pre) {
  const s = pre.querySelector("svg");
  if (!s) return;
  s.removeAttribute("height");
  s.style.maxWidth = "100%";
  s.style.maxHeight = "72vh";
}

/** Render every not-yet-done <pre.mermaid> inside `root`. */
export async function renderMermaidIn(root) {
  const blocks = root.querySelectorAll("pre.mermaid:not([data-mmd])");
  if (!blocks.length) return;

  const mm = await ensureMermaid();
  if (!mm) return;   // offline / blocked — leave the source visible

  for (const pre of blocks) {
    const code = pre.textContent.trim();
    if (!code) continue;
    pre.dataset.mmd = "1";

    if (svgCache.has(code)) {
      const cached = svgCache.get(code);
      if (cached) { pre.innerHTML = cached; pre.classList.add("rendered"); fitSvg(pre); }
      else { pre.classList.add("mermaid-error"); delete pre.dataset.mmd; }
      continue;
    }

    try {
      const { svg } = await mm.render(`mmd-${Date.now()}-${idc++}`, code);
      svgCache.set(code, svg);
      pre.innerHTML = svg;
      pre.classList.add("rendered");
      pre.classList.remove("mermaid-error");
      fitSvg(pre);
    } catch {
      svgCache.set(code, null);
      pre.classList.add("mermaid-error");
      delete pre.dataset.mmd;   // let a later (complete) render retry
    }
  }
}
