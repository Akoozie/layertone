"""Layertone logo options: a mark plus a wordmark, as clean one-colour vector SVGs.

Status 2026-10-28: exploration, not a final logo. After 3 graded passes the best (tone
rings, below) scored 6/10 from a fresh reviewer: reads as a target or audio ripple, and
repeats the card's contour field. The two-weight wordmark was the strongest part.

Every shape is drawn in mm at card size (mark 12 mm tall) so it can be checked against
the engrave rules: grooves >= 0.45 mm, white ridges between them >= 0.5 mm. The SVGs
scale to any size. Text is outlined (no font needed to open them).

Needs fonttools and uharfbuzz (pip install fonttools uharfbuzz), only for this script.
Run: python examples/logo/make_logo.py  (writes the SVGs next to this file)
"""
from pathlib import Path
import math

FONTS = Path(__file__).resolve().parents[2] / "src" / "layertone" / "fonts"
INK = "#161616"
S = 12.0                    # mm, mark size at card scale


def outline_text(s, font, em, x=0.0, y=0.0, track=0.0):
    """SVG path data of `s` set in `font` (a file in FONTS) at `em` mm, baseline at y,
    shaped with HarfBuzz (kerning on). Returns (path data, advance width in mm)."""
    import uharfbuzz as hb
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    data = (FONTS / font).read_bytes()
    face = hb.Face(data)
    hbfont = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(s)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, {"kern": True, "liga": True})
    tt = TTFont(FONTS / font)
    gs, order, upm = tt.getGlyphSet(), tt.getGlyphOrder(), tt["head"].unitsPerEm
    k = em / upm
    pen = SVGPathPen(gs, lambda v: f"{v:.3f}".rstrip("0").rstrip("."))
    cx = x
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        tp = TransformPen(pen, (k, 0, 0, -k, cx + pos.x_offset * k, y - pos.y_offset * k))
        gs[order[info.codepoint]].draw(tp)
        cx += pos.x_advance * k + track * em
    return pen.getCommands(), cx - x - track * em


def rrect(x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    return (f"M{x + r:.3f},{y:.3f}H{x + w - r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x + w:.3f},{y + r:.3f}"
            f"V{y + h - r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x + w - r:.3f},{y + h:.3f}H{x + r:.3f}"
            f"A{r:.3f},{r:.3f} 0 0 1 {x:.3f},{y + h - r:.3f}V{y + r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x + r:.3f},{y:.3f}Z")


# ---- marks, each in a 10 x 10 mm box at the origin --------------------------------

def _ramp_bands(n=6, g0=0.45, g1=1.2, size=10.0):
    """(y, height) of n engraved bands on an even pitch, thin at the top and thick at
    the bottom: a tone ramp made of layer lines. Grooves g0 -> g1 mm; the ridges between
    them stay >= 0.5 mm at card size (10 mm)."""
    p = size / n
    out = []
    for i in range(n):
        h = g0 + (g1 - g0) * i / (n - 1)
        out.append(((i + 1) * p - h - (p - g1) / 2, h))
    return out


def mark_sphere():
    """Tone sphere: a disc of layer lines that thicken downwards, so it reads as a ball
    lit from above. It is the app in one shape: tone made by layer thickness."""
    clip = f'<clipPath id="s"><circle cx="{S / 2}" cy="{S / 2}" r="{S / 2}"/></clipPath>'
    bands = "".join(f'<rect x="0" y="{y:.3f}" width="{S}" height="{h:.3f}"/>' for y, h in _ramp_bands(6, 0.45, 1.5, S))
    return clip + f'<g clip-path="url(#s)">{bands}</g>'


def mark_tile():
    """Tone tile: the same ramp in a rounded square with the card's corner ratio,
    a printed swatch."""
    clip = f'<clipPath id="t"><path d="{rrect(0, 0, S, S, 2.4)}"/></clipPath>'
    bands = "".join(f'<rect x="0" y="{y:.3f}" width="{S}" height="{h:.3f}"/>' for y, h in _ramp_bands(6, 0.45, 1.5, S))
    return clip + f'<g clip-path="url(#t)">{bands}</g>'


def mark_peak():
    """Contour peak: four nested rings of a hill seen from above, their centres drifting
    up and right so the lines crowd on one side, like the card's contour field."""
    rings = [(5.0, 5.0, 4.7), (5.6, 4.4, 3.35), (6.15, 3.85, 2.05), (6.6, 3.4, 0.85)]
    return '<g transform="scale(1.2)">' + "".join(
        f'<circle cx="{x}" cy="{y}" r="{r:.3f}" fill="none" stroke="{INK}" stroke-width="0.6"/>' for x, y, r in rings) + "</g>"


def mark_steps():
    """Stacked L: three rounded layers, shortest on top, left aligned. Reads as a stack
    of printed layers and as a stepped capital L."""
    h, g = 2.6, 1.1
    rows = [(4.0, 0), (7.0, 1), (10.0, 2)]
    return '<g transform="scale(1.2)">' + "".join(f'<path d="{rrect(0, i * (h + g), L, h, 0.5)}"/>' for L, i in rows) + "</g>"


def _ring(x, y, w, h, r, t):
    """A rounded-square outline t mm thick, as one even-odd path."""
    return rrect(x, y, w, h, r) + rrect(x + t, y + t, w - 2 * t, h - 2 * t, max(0.0, r - t))


def mark_overlap():
    """Two layers, overlapped: two rounded-square outlines offset on the diagonal, the
    part where they overlap solid. Where layers stack, the tone deepens."""
    a, o, t, r = 8.2, S - 8.2, 0.75, 2.0
    return (f'<path fill-rule="evenodd" d="{_ring(0, 0, a, a, r, t)}"/>'
            f'<path fill-rule="evenodd" d="{_ring(o, o, a, a, r, t)}"/>'
            f'<path d="{rrect(o, o, a - o, a - o, 0.6)}"/>')


def mark_hill():
    """Sliced hill: a dome cut into five printed layers, widest on the bed. The card's
    contour hill seen from the side, the way the slicer sees it."""
    n, g = 5, 0.7
    h = (S - (n - 1) * g) / n
    out = []
    for i in range(n):                      # i = 0 is the bed
        yc = (i + 0.5) / n
        w = S * (1 - yc ** 1.6) ** 0.5
        y = S - (i + 1) * h - i * g
        out.append(f'<path d="{rrect((S - w) / 2, y, w, h, h / 2)}"/>')
    return "".join(out)


def _arc_ring(cx, cy, r, w, gap_deg, at_deg):
    """A circle outline w mm wide with a break of gap_deg centred at at_deg (0 = right,
    90 = down, SVG angles), ends cut square along the radius."""
    a0, a1 = math.radians(at_deg + gap_deg / 2), math.radians(at_deg + 360 - gap_deg / 2)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    return (f'<path d="M{x0:.3f},{y0:.3f}A{r:.3f},{r:.3f} 0 1 1 {x1:.3f},{y1:.3f}" fill="none" stroke="{INK}" '
            f'stroke-width="{w}"/>')


def mark_rings(rings=((0.8, 0.65), (0.72, 0.45), (0.9, 0.15)), ridge=0.5, gap_deg=35):
    """Tone rings: a hill seen from above, as on the card. Contour rings that get thicker
    towards a solid summit (the tone deepens with height), their centres pushed hard up
    and right so the slope is steep there and gentle at the lower left, where the outer
    ring opens. rings: (groove mm, drift of the next centre mm). Ridges >= 0.5 mm."""
    u = (math.sqrt(0.5), -math.sqrt(0.5))                # up and right
    cx = cy = S / 2
    R, out = S / 2, []
    for i, (g, d) in enumerate(rings):
        rc = R - g / 2
        out.append(_arc_ring(cx, cy, rc, g, gap_deg, 135) if i == 0 else
                   f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{rc:.3f}" fill="none" stroke="{INK}" stroke-width="{g}"/>')
        inner = R - g
        cx, cy = cx + d * u[0], cy + d * u[1]
        R = inner - ridge - d                            # tight side keeps one ridge
    out.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{R:.3f}"/>')
    return "".join(out)


def mark_shear():
    """Layer shift: a square cut into five layers on an even pitch, each pushed a step
    further right, like a print whose layers shifted. The top right corner is cut by an
    arc: the card's hill rising off that corner."""
    n, ridge = 5, 0.6
    h = (S - (n - 1) * ridge) / n
    clip = f'<clipPath id="h"><path d="M0,0H{S * 0.42:.3f}A{S * 0.58:.3f},{S * 0.58:.3f} 0 0 1 {S},{S * 0.58:.3f}V{S}H0Z"/></clipPath>'
    bands = "".join(f'<rect x="{-1 + i * 0.55:.3f}" y="{i * (h + ridge):.3f}" width="{S + 1:.3f}" height="{h:.3f}"/>'
                    for i in range(n))
    return clip + f'<g clip-path="url(#h)"><g transform="translate(0,0)">{bands}</g></g>'


def mark_sphere2():
    """Tone sphere, cleaner: an outer ring holds the circle; inside, layer lines with a
    constant 0.55 mm white gap whose grooves thicken downwards (0.45 -> 1.4 mm), under a
    white cap, so it reads as a ball lit from above, not a striped sun."""
    ring, gap = 0.5, 0.55
    ri = S / 2 - ring - gap
    clip = f'<clipPath id="q"><circle cx="{S / 2}" cy="{S / 2}" r="{ri:.3f}"/></clipPath>'
    n, g0, g1 = 6, 0.45, 1.4
    y, bands = S / 2 + ri, []
    for i in range(n):
        g = g1 - (g1 - g0) * i / (n - 1)
        y -= g
        bands.append(f'<rect x="0" y="{y:.3f}" width="{S}" height="{g:.3f}"/>')
        y -= gap
    return (f'<circle cx="{S / 2}" cy="{S / 2}" r="{S / 2 - ring / 2}" fill="none" stroke="{INK}" stroke-width="{ring}"/>'
            + clip + f'<g clip-path="url(#q)">{"".join(bands)}</g>')


def mark_swatch():
    """Tone swatch: a rounded square in four cells that darken in reading order, made the
    way a print makes tone: an empty frame, thin layer lines, thick layer lines, solid.
    Like the TD calibration swatches the app prints. Grooves >= 0.5, ridges >= 0.55 mm."""
    g, c = 0.7, (S - 0.7) / 2                           # gutter, cell size
    clip = f'<clipPath id="w"><path d="{rrect(0, 0, S, S, 2.0)}"/></clipPath>'

    def lines(x, y, groove, ridge):
        n = round((c + ridge) / (groove + ridge))
        pitch = (c + ridge) / n                         # stretch so the cell starts and ends on a groove
        gr = pitch - ridge
        return "".join(f'<rect x="{x:.3f}" y="{y + i * pitch:.3f}" width="{c:.3f}" height="{gr:.3f}"/>' for i in range(n))
    t = 0.55
    frame = f'<path fill-rule="evenodd" d="{rrect(0, 0, c, c, 0) + rrect(t, t, c - 2 * t, c - 2 * t, 0)}"/>'
    cells = frame + lines(c + g, 0, 0.5, 1.1) + lines(0, c + g, 1.1, 0.55) + f'<rect x="{c + g:.3f}" y="{c + g:.3f}" width="{c:.3f}" height="{c:.3f}"/>'
    return clip + f'<g clip-path="url(#w)">{cells}</g>'


MARKS = {"rings": mark_rings}


# ---- lockups ------------------------------------------------------------------------

def wordmark(x, baseline, em, track=-0.015):
    """'layer' in Inter Display Medium, 'tone' in Bold: the name's two halves."""
    d1, w1 = outline_text("layer", "InterDisplay-Medium.otf", em, x, baseline, track)
    d2, w2 = outline_text("tone", "InterDisplay-Bold.otf", em, x + w1 + track * em, baseline, track)
    return f'<path d="{d1}"/><path d="{d2}"/>', w1 + track * em + w2


def lockup(mark, em=None, gap=None, track=-0.015):
    """Mark left, wordmark right. The mark is 92 % of the wordmark's ascender-to-
    descender span (Inter Display: 0.757 + 0.2 em), centred on the x-height, and sits
    0.6 x-heights from the l. Returns (body, width, height)."""
    em = em or S / (0.92 * 0.957)
    xh = 0.53 * em
    gap = gap if gap is not None else 0.6 * xh
    base = S / 2 + xh / 2
    wm, w = wordmark(S + gap, base, em, track)
    top = min(0.0, base - 0.757 * em)
    return MARKS[mark]() + wm, S + gap + w, (top, max(S, base + 0.2 * em))


def svg_doc(body, w, h, pad=0.0, bg=None, fill=INK):
    b = f'<rect x="{-pad}" y="{-pad}" width="{w + 2 * pad}" height="{h + 2 * pad}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 2 * pad:.2f}mm" height="{h + 2 * pad:.2f}mm" '
            f'viewBox="{-pad:.3f} {-pad:.3f} {w + 2 * pad:.3f} {h + 2 * pad:.3f}">{b}<g fill="{fill}">{body}</g></svg>\n')


if __name__ == "__main__":
    here = Path(__file__).parent
    for name in MARKS:
        body, w, (y0, y1) = lockup(name)
        (here / f"layertone_{name}.svg").write_text(svg_doc(f'<g transform="translate(0,{-y0:.3f})">{body}</g>', w, y1 - y0), encoding="utf-8")
        (here / f"layertone_{name}_mark.svg").write_text(svg_doc(MARKS[name](), S, S), encoding="utf-8")
        print("wrote", name)
