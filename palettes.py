"""Export colour palettes.

15 palettes transcribed from the reference image plus a plain ``classic``.
Each entry maps the source swatches onto document roles, hand-tuned so body
text stays readable:

  bg       page background
  text     body text
  heading  h1/h2/h3
  accent   links, cover band, TOC markers, rules
  muted    captions, borders, secondary text
"""

from __future__ import annotations

PALETTES: dict[str, dict[str, str]] = {
    "classic":     {"label": "Classic",     "bg": "#FFFFFF", "text": "#1F2430", "heading": "#111418", "accent": "#3355DD", "muted": "#6B7280"},
    "warm":        {"label": "Warm",        "bg": "#FFFBF2", "text": "#3B3838", "heading": "#F77575", "accent": "#90AACB", "muted": "#B79B86"},
    "cool":        {"label": "Cool",        "bg": "#F4FAFE", "text": "#010038", "heading": "#3282B8", "accent": "#00909E", "muted": "#7FA9C3"},
    "soft":        {"label": "Soft",        "bg": "#FBF8F1", "text": "#4B4D63", "heading": "#4B4D63", "accent": "#8A9DA4", "muted": "#B8B29C"},
    "powerful":    {"label": "Powerful",    "bg": "#FFFDF6", "text": "#101828", "heading": "#0F2C67", "accent": "#CD1818", "muted": "#F3950D"},
    "modern":      {"label": "Modern",      "bg": "#FCF7EC", "text": "#3F3330", "heading": "#7D5A50", "accent": "#9E7777", "muted": "#C9A99A"},
    "futuristic":  {"label": "Futuristic",  "bg": "#FBFAFE", "text": "#11052C", "heading": "#3D087B", "accent": "#F43B86", "muted": "#8A7CA8"},
    "natural":     {"label": "Natural",     "bg": "#FBF9EF", "text": "#323232", "heading": "#096C47", "accent": "#0B8457", "muted": "#8FAE9B"},
    "exclusive":   {"label": "Exclusive",   "bg": "#FBF6EE", "text": "#2D2424", "heading": "#5C3D2E", "accent": "#B85C38", "muted": "#B99A79"},
    "popular":     {"label": "Popular",     "bg": "#FEFBF3", "text": "#2E2E2E", "heading": "#3A6E71", "accent": "#79B4B7", "muted": "#9D9D9D"},
    "romantic":    {"label": "Romantic",    "bg": "#FFF6F8", "text": "#251F44", "heading": "#E36387", "accent": "#A6DCEF", "muted": "#C89BA8"},
    "vintage":     {"label": "Vintage",     "bg": "#F7FBF9", "text": "#4B4342", "heading": "#766161", "accent": "#87A7B3", "muted": "#B9B3A8"},
    "traditional": {"label": "Traditional", "bg": "#FBF9F0", "text": "#393232", "heading": "#3A6351", "accent": "#E48257", "muted": "#A99C7E"},
    "dark":        {"label": "Dark",        "bg": "#1E1B22", "text": "#E7E4EA", "heading": "#F1EEF4", "accent": "#CA3E47", "muted": "#9A93A0"},
    "midnight":    {"label": "Midnight",    "bg": "#0B1020", "text": "#D6E2F5", "heading": "#FFFFFF", "accent": "#3282B8", "muted": "#7C8BA8"},
}

DEFAULT = "popular"


def get(name: str | None) -> dict[str, str]:
    return PALETTES.get(name or DEFAULT, PALETTES[DEFAULT])
