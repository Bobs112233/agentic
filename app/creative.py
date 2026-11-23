"""Turns a creative spec chosen by the Creative Director agent into a 1080x1080 SVG ad.
All text is escaped and all colours validated, so model output can never inject markup."""
import hashlib
import re
from html import escape as _escape, unescape

def escape(text: str) -> str:
    """Models sometimes send text that is already HTML-escaped; normalise before escaping once."""
    return _escape(unescape(str(text)))


LAYOUTS = ("bold", "split", "minimal")
MOTIFS = ("rings", "grid", "burst")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _colour(value: str, fallback: str) -> str:
    return value if isinstance(value, str) and _HEX.match(value) else fallback


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _shade(hex_colour: str, factor: float) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * factor))) for c in (r, g, b))


def _wrap(text: str, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines[:5]


def _motif(kind: str, cx: int, cy: int, colour: str) -> str:
    if kind == "rings":
        return "".join(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colour}" stroke-width="3" opacity="{0.7 - i * 0.11:.2f}"/>'
            for i, r in enumerate(range(90, 500, 80)))
    if kind == "grid":
        return "".join(
            f'<circle cx="{cx - 300 + col * 60}" cy="{cy - 300 + line * 60}" r="5" fill="{colour}" opacity="{0.25 + ((col + line) % 4) * 0.15:.2f}"/>'
            for line in range(11) for col in range(11))
    rays = "".join(
        f'<rect x="{cx - 5}" y="{cy - 430}" width="10" height="{250 + (i % 3) * 60}" rx="5" fill="{colour}" '
        f'opacity="{0.25 + (i % 3) * 0.2:.2f}" transform="rotate({i * 20} {cx} {cy})"/>' for i in range(18))
    return rays + f'<circle cx="{cx}" cy="{cy}" r="70" fill="{colour}"/>'


def render_svg(spec: dict, headline: str, cta: str, business: str) -> str:
    layout = spec.get("layout") if spec.get("layout") in LAYOUTS else "bold"
    motif = spec.get("motif") if spec.get("motif") in MOTIFS else "rings"
    bg = _colour(spec.get("bg_color"), "#0b1020")
    accent = _colour(spec.get("accent_color"), "#22d3ee")
    badge = escape(str(spec.get("badge", ""))[:24])
    ink = "#ffffff" if _luminance(bg) < 0.55 else "#0b1020"
    on_accent = "#ffffff" if _luminance(accent) < 0.55 else "#0b1020"

    lines = _wrap(headline, 11 if layout == "split" else 16)
    size = 104 if len(lines) <= 3 else 84
    if layout == "split":
        size -= 22
    anchor, x = ("middle", 540) if layout == "minimal" else ("start", 84)
    block = len(lines) * size * 1.1
    top = 540 - block / 2 + size * 0.8

    text = "".join(
        f'<text x="{x}" y="{top + i * size * 1.1:.0f}" text-anchor="{anchor}" font-size="{size}" '
        f'font-weight="800" fill="{ink}" letter-spacing="-2">{escape(line)}</text>' for i, line in enumerate(lines))

    if layout == "split":
        art = (f'<rect x="700" width="380" height="1080" fill="{accent}"/>'
               + _motif(motif, 890, 540, on_accent))
    elif layout == "minimal":
        art = (f'<rect x="40" y="40" width="1000" height="1000" rx="36" fill="none" stroke="{accent}" stroke-width="6"/>'
               f'<g opacity="0.35">{_motif(motif, 540, 540, accent)}</g>')
    else:
        art = f'<g opacity="0.9">{_motif(motif, 900, 220, accent)}</g>'

    cta_text = escape(cta[:22])
    cta_width = 90 + len(cta_text) * 24
    cta_x = 540 - cta_width / 2 if layout == "minimal" else 84
    badge_x = 540 - (60 + len(badge) * 19) / 2 if layout == "minimal" else 84
    badge_svg = (
        f'<rect x="{badge_x:.0f}" y="84" width="{60 + len(badge) * 19}" height="58" rx="29" fill="{accent}"/>'
        f'<text x="{badge_x + 30:.0f}" y="123" font-size="30" font-weight="700" fill="{on_accent}">{badge}</text>'
    ) if badge else ""

    # Several ads sit on one page, so every gradient needs its own id.
    gid = "g" + hashlib.md5(f"{bg}{accent}{layout}{headline}".encode()).hexdigest()[:8]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1080" '
        'font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="{_shade(bg, 0.55 if _luminance(bg) < 0.55 else 0.9)}"/></linearGradient></defs>'
        f'<rect width="1080" height="1080" fill="url(#{gid})"/>{art}{badge_svg}{text}'
        f'<rect x="{cta_x:.0f}" y="900" width="{cta_width}" height="84" rx="42" fill="{accent}"/>'
        f'<text x="{cta_x + cta_width / 2:.0f}" y="954" text-anchor="middle" font-size="36" font-weight="700" '
        f'fill="{on_accent}">{cta_text}</text>'
        f'<text x="{996 if layout != "split" else 660}" y="1010" text-anchor="end" font-size="28" font-weight="600" '
        f'fill="{ink}" opacity="0.7">{escape(business[:28])}</text></svg>'
    )
