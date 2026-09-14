# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Deterministic (regex/static) checks for the automatic design gates.

Each check receives (html, css) text and returns True when the gate FAILS.
Checks are pure text analysis — OBJECTIVE evidence, no rendering, no LLM.
Adapted from Hallmark's slop test (github.com/nutlope/hallmark, MIT).
"""

from __future__ import annotations

import re
from collections.abc import Callable

Check = Callable[[str, str], bool]

_DEFAULT_FONTS = {"inter", "roboto", "open sans", "poppins", "lato", "sans-serif", "system-ui"}
_EMOJI_ICONS = ("✨", "🚀", "⚡", "🔥", "🎯", "✅")
_CLICHE = re.compile(r"\b(jane doe|john smith|acme|nexus|seamless|unleash)\b", re.I)
_CSS_BLOCKS = re.compile(r"([^{}]+)\{([^{}]*?)\}")


def _blocks(css: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _CSS_BLOCKS.finditer(css)]


def _g1(html: str, css: str) -> bool:
    for m in re.finditer(r"font-family:\s*([^;]+)", css):
        first = m.group(1).split(",")[0].strip().strip("'\"").lower()
        if first in _DEFAULT_FONTS:
            return True
    return False


def _g2(html: str, css: str) -> bool:
    if re.search(r"background-clip:\s*text", css):
        return True
    purple_blue = r"linear-gradient\([^)]*#(8b5cf6|a855f7|7c3aed|6366f1)[^)]*#(3b82f6|2563eb|06b6d4|0ea5e9)"
    return bool(re.search(purple_blue, css, re.I))


def _g3(html: str, css: str) -> bool:
    return bool(re.search(r"grid-template-columns:\s*repeat\(\s*3\b", css))


def _g6(html: str, css: str) -> bool:
    return bool(re.search(r"min-height:\s*100vh", css) and re.search(r"text-align:\s*center", css))


def _g7(html: str, css: str) -> bool:
    return bool(re.search(r"#(000|fff|000000|ffffff)\b", css, re.I))


def _g10(html: str, css: str) -> bool:
    return bool(re.search(r"transition(-property)?:\s*[^;}]*\ball\b", css) or "transition-all" in css)


def _g11(html: str, css: str) -> bool:
    return bool(re.search(r"scale-105|scale\(1\.05\)", css))


def _g12(html: str, css: str) -> bool:
    return bool(re.search(r"cubic-bezier\([^)]*1\.\d+", css))


def _g14(html: str, css: str) -> bool:
    return bool(re.search(r"transition[^;:]*:\s*[^;]*\b(width|height|top|left|margin|padding)\b", css))


def _g19(html: str, css: str) -> bool:
    return bool(_CLICHE.search(html))


def _g20(html: str, css: str) -> bool:
    return not re.search(r"/\*[^*]*(Mekong Design|macrostructure:)", css)


def _g22(html: str, css: str) -> bool:
    return bool(re.search(r"oklch\(\s*[\d.]+%?\s+0(?:\.0+)?\s+[\d.]+", css))


def _g24(html: str, css: str) -> bool:
    for m in re.finditer(r"(?:padding|margin|gap)[^;:]*:\s*([^;]+)", css):
        if any(int(px) % 4 for px in re.findall(r"(\d+)px", m.group(1))):
            return True
    return False


def _g25(html: str, css: str) -> bool:
    return any(not 45 <= int(m.group(1)) <= 75 for m in re.finditer(r"max-width:\s*(\d+)ch", css))


def _g26(html: str, css: str) -> bool:
    if not re.search(r"<(button|a|input|select|textarea)\b", html):
        return False
    return not re.search(r":focus-visible", css)


def _g27(html: str, css: str) -> bool:
    has_motion = bool(re.search(r"@keyframes|animation:", css))
    return has_motion and "prefers-reduced-motion" not in css


def _g28(html: str, css: str) -> bool:
    for m in re.finditer(r"<video\b[^>]*>", html):
        tag = m.group(0)
        if "autoplay" in tag and "poster" not in tag:
            return True
    return False


def _g30(html: str, css: str) -> bool:
    return any(icon in html for icon in _EMOJI_ICONS)


def _g33(html: str, css: str) -> bool:
    if "<svg" not in html:
        return False
    return not re.search(r'aria-hidden\s*=\s*"true"|aria-label', html)


def _g34(html: str, css: str) -> bool:
    return not re.search(r"overflow-x:\s*clip", css)


def _g37(html: str, css: str) -> bool:
    families = set()
    for m in re.finditer(r"font-family:\s*([^;]+)", css):
        for token in m.group(1).split(","):
            name = token.strip().strip("'\"").lower()
            if name:
                families.add(name)
    return len(families) > 3


def _g38a(html: str, css: str) -> bool:
    for selector, body in _blocks(css):
        if re.search(r"font-style:\s*italic", body) and re.search(r"(^|[,\s])h[1-6]\b|\btitle|wordmark", selector, re.I):
            return True
    return False


def _g47(html: str, css: str) -> bool:
    return bool(re.search(r"traffic-light|window-dot|browser-bar|phone-frame|fake-terminal|mock-browser", html + css, re.I))


def _g48(html: str, css: str) -> bool:
    if not re.search(r":root|\[data-theme", css):
        return False
    stripped = re.sub(r"(:root|\[data-theme[^\]]*\])\s*\{[^{}]*\}", "", css)
    return bool(re.search(r"#[0-9a-f]{3,8}\b|oklch\(|rgba?\(|hsla?\(", stripped, re.I))


def _g50(html: str, css: str) -> bool:
    if not re.search(r"<img\b|<picture\b", html):
        return False
    for m in re.finditer(r"grid-template-columns:\s*([^;]+)", css):
        decl = m.group(1)
        # Strip every minmax(0, 1fr) wrapper — those are safe.
        stripped = re.sub(r"minmax\(\s*0\s*,\s*1fr\s*\)", "", decl)
        if re.search(r"\b1fr\b", stripped):
            return True
    return False


def _g51(html: str, css: str) -> bool:
    if not re.search(r"<h1\b", html):
        return False
    return not re.search(r"overflow-wrap:\s*anywhere", css)


def _g54(html: str, css: str) -> bool:
    for selector, body in _blocks(css):
        if not re.search(r"__head|__intro|section-head", selector):
            continue
        m = re.search(r"grid-template-columns:\s*([^;]+)", body)
        if not m:
            continue
        decl = m.group(1).strip()
        # Single-column layouts pass: bare 1fr or a single minmax(0, 1fr).
        if decl == "1fr" or decl == "minmax(0, 1fr)" or decl == "minmax(0,1fr)":
            continue
        # Anything with more than one track is the banned eyebrow-beside-heading shape.
        stripped = re.sub(r"minmax\(\s*0\s*,\s*1fr\s*\)", "X", decl)
        if len(stripped.split()) > 1:
            return True
    return False


def _g55(html: str, css: str) -> bool:
    for _selector, body in _blocks(css):
        if not re.search(r"text-transform:\s*uppercase", body):
            continue
        m = re.search(r"line-height:\s*([\d.]+)", body)
        if m and float(m.group(1)) < 1.0:
            return True
    return False


def _g56(html: str, css: str) -> bool:
    sticky_top_zero = sum(
        1
        for _selector, body in _blocks(css)
        if re.search(r"position:\s*sticky", body) and re.search(r"top:\s*0\b", body)
    )
    return sticky_top_zero >= 2


CHECKS: dict[str, Check] = {
    "1": _g1, "2": _g2, "3": _g3, "6": _g6, "7": _g7, "10": _g10, "11": _g11,
    "12": _g12, "14": _g14, "19": _g19, "20": _g20, "22": _g22, "24": _g24,
    "25": _g25, "26": _g26, "27": _g27, "28": _g28, "30": _g30, "33": _g33,
    "34": _g34, "37": _g37, "38a": _g38a, "47": _g47, "48": _g48, "50": _g50,
    "51": _g51, "54": _g54, "55": _g55, "56": _g56,
}
