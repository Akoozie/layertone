"""Business cards: 85 x 55 mm cards with raised text, an optional picture and QR code.

A card is a Layered print with a fixed Swap plan: every filament in the Stack
gets a band of layers thick enough to hide the one below, so text, rules and
QR modules raised to the top of a band show that filament crisply. A picture
can be a layered photo (the bands' Palette, like the main mode) or a
one-colour logo. Swaps happen at whole-plate heights, so a plate of 8 cards
still has only one filament change per Swap.

Text is drawn in Inter Bold, thickened where needed so no stroke is thinner
than MIN_STROKE (about one 0.4 mm nozzle line).
"""
import argparse
from dataclasses import dataclass, field
from math import ceil, log
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .filaments import pick
from .mesh import heightfield_mesh, mask_mesh
from .optics import TD_SCALE, srgb_to_lab, stack_colours
from .pipeline import fit, open_image
from .plan import Plan, despeckle, heights
from .threemf import write_3mf, write_flat_3mf

CARD_MM = (85.0, 55.0)
MARGIN = 5.0
MIN_STROKE = 0.45          # mm; one 0.4 mm nozzle line, a bit over
ENGRAVE_STROKE = 0.8       # mm; engraved grooves: two nozzle lines. 0.45 mm grooves in 2 mm caps filled in on the A1 (TEST4)
ENGRAVE_CAP = 5.0          # mm; smallest cap height that engraves cleanly on a 0.4 nozzle; below it, print face down
CAP = 0.727                # Inter's cap height as a share of the em
ENGRAVE_RIDGE = 0.5        # mm; thinnest card-colour wall left between grooves (counters, letter gaps)
INLAY_STROKE = 0.42        # mm; Bambu's 0.4 mm nozzle line width. Flush inlays have no side walls or shadows to fatten them
SMOOTH_PLATE = "High Temp Plate"   # Bambu's smooth PEI; the face of a face-down card takes the plate's finish (default: textured PEI)
INLAY_LAYER = 0.16         # mm; face-down inlays are flat, so finer Z adds swaps, not sharpness
MIN_EM = 2.6               # mm; smaller Inter Bold fills its own counters once thickened
THIN = 0.11                # Inter Bold's thinnest strokes (the bars of e, a) as a share of the em
QR_MODULE = 1.0            # mm per QR square; phones read 1 mm squares from ~15 cm
FONT = Path(__file__).with_name("fonts") / "Inter-Bold.otf"
BAND_MIN, BAND_MAX = 5, 12  # layers per band: 0.4 mm keeps raised text sturdy, 0.96 mm is plenty
CORNER = 2.5               # mm, corner radius; 3 mm already reads like a credit card
RAISE = 5                  # layers an SVG's class="raise" shapes stand above the top band (0.4 mm)
PLATE = (256.0, 256.0)     # A1 bed
GAP = 5.0


def card_plan(filaments, base_layers=5, thickness=1.2, first_layer=0.2, layer_h=0.08, extra=0):
    """Plan with one opaque band per filament above the base. Backing (0.2 mm
    layers) brings the thinnest part of the card up to `thickness` mm. `extra`
    layers of the top filament go above its band, for embossed shapes."""
    swaps, top = [], base_layers
    for f in filaments[1:]:
        swaps.append(top)
        # layers to hide 90% of what is under it
        top += int(np.clip(ceil(f.td * TD_SCALE * log(10) / layer_h - 1e-9), BAND_MIN, BAND_MAX))
    plan = Plan(filaments, swaps, base_layers, top + extra, first_layer, layer_h)
    plan.extra = extra
    plan.backing = round(ceil(max(0.0, thickness - float(plan.z_top(base_layers))) / 0.2 - 1e-6) * 0.2, 1)
    return plan


def level(plan, k):
    """Height (layers) whose top shows filament k: the top of its band."""
    return plan.swaps[k] if k < len(plan.swaps) else plan.max_layers - getattr(plan, "extra", 0)


def outline(shape, px, corner=CORNER, soft=False):
    """Pixels inside the card's rounded rectangle (soft = coverage 0..1 for previews)."""
    h, w = shape
    W, H = w * px, h * px
    xs, ys = (np.arange(w) + 0.5) * px, (np.arange(h) + 0.5) * px
    dx = np.maximum(np.abs(xs - W / 2) - (W / 2 - corner), 0)
    dy = np.maximum(np.abs(ys - H / 2) - (H / 2 - corner), 0)
    d = np.hypot(dy[:, None], dx[None, :]) - corner          # signed distance to the edge, < 0 inside
    return np.clip(0.5 - d / px, 0, 1) if soft else d <= 0


@dataclass
class CardSpec:
    lines: list                       # text lines; the first is the name
    stack: list = field(default_factory=lambda: ["jade_white", "blue", "black"])
    background: int = 0               # Stack index of the card face
    ink: int = -1                     # Stack index of the text (-1 = top filament)
    accent: int = 1                   # Stack index of the rule, border and logo
    qr: str = ""
    picture: object = None            # PIL image or None
    picture_mode: str = "photo"       # "photo" = layered, "logo" = one colour in the accent
    rule: bool = True                 # a short bar under the name
    border: float = 0.0               # mm, raised edge in the accent
    thickness: float = 1.2            # mm at the thinnest point of the card
    corner: float = CORNER            # mm corner radius (0 = square)
    engrave: bool = False             # set by engraved(): text is cut into the face


@dataclass
class CardResult:
    plan: Plan
    z: np.ndarray                     # top Z in mm per pixel (anti-aliased edges)
    colour: np.ndarray                # (h, w, 3) sRGB preview
    px: float
    warnings: list
    corner: float = CORNER

    def mask(self):
        return outline(self.z.shape, self.px, self.corner) if self.corner else None

    def preview(self):
        im = Image.fromarray((self.colour * 255).round().astype(np.uint8))
        if self.corner:
            im.putalpha(Image.fromarray((outline(self.z.shape, self.px, self.corner, True) * 255).round().astype(np.uint8)))
        return im


def _font(em_mm, px):
    return ImageFont.truetype(str(FONT), max(4, round(em_mm / px)))


def _text_cov(shape, xy, text, em, px, align="left"):
    """Coverage 0..1 of one line, thickened so its thinnest strokes reach MIN_STROKE."""
    stroke = max(0.0, (MIN_STROKE - THIN * em) / 2)
    im = Image.new("L", shape[::-1], 0)
    ImageDraw.Draw(im).text((xy[0] / px, xy[1] / px), text, font=_font(em, px), fill=255, anchor="ls" if align == "left" else "ms",
                            stroke_width=round(stroke / px), stroke_fill=255)
    return np.asarray(im, dtype=np.float64) / 255


def _width(text, em, px):
    stroke = max(0.0, (MIN_STROKE - THIN * em) / 2)
    l, _, r, _ = _font(em, px).getbbox(text, anchor="ls")
    return (r - l) * px + 2 * stroke


def _rect(shape, px, x0, y0, x1, y1):
    """Coverage of a rectangle in mm, with soft (sub-pixel) edges."""
    h, w = shape
    xs = (np.arange(w) + 0.5) * px
    ys = (np.arange(h) + 0.5) * px
    cx = np.clip(np.minimum(xs + px / 2, x1) - np.maximum(xs - px / 2, x0), 0, px) / px
    cy = np.clip(np.minimum(ys + px / 2, y1) - np.maximum(ys - px / 2, y0), 0, px) / px
    return cy[:, None] * cx[None, :]


def qr_matrix(text):
    import segno
    q = segno.make(text, error="m", boost_error=False, micro=False)     # phones rarely read Micro QR
    return np.array([[bool(v) for v in row] for row in q.matrix])


def engraved(spec, dark_top=True):
    """The same CardSpec with the card face moved to the top of the Stack, so text and
    shapes are cut into it instead of standing on it (one swap for two filaments).

    dark_top: the darkest filament becomes the face and the lightest shows in the grooves.
    A dark top hides what is under it in 0.4 mm, so the grooves are shallow and open and
    the card is about 1 mm thick; a light top needs 0.9 mm and makes deep, narrow slots."""
    n = len(spec.stack)
    bg, ink = spec.background % n, spec.ink % n
    if dark_top:
        lum = [srgb_to_lab(np.array(f.rgb))[0] for f in pick(spec.stack)]
        if lum[bg] > min(lum):
            bg, ink = int(np.argmin(lum)), int(np.argmax(lum))
    order = [i for i in range(n) if i != bg] + [bg]
    at = {old: new for new, old in enumerate(order)}
    from dataclasses import replace
    return replace(spec, stack=[spec.stack[i] for i in order], background=n - 1,
                   ink=at[ink], accent=at[spec.accent % n], thickness=0.6, engrave=True)


def make_card(spec, px=0.08):
    fils = pick(spec.stack)
    n = len(fils)
    ink, accent, bg = spec.ink % n, spec.accent % n, spec.background % n
    plan = card_plan(fils, thickness=spec.thickness)
    pal = plan.palette()
    W, H = CARD_MM
    shape = (round(H / px), round(W / px))
    warn = []
    zof = lambda k: float(plan.z_top(level(plan, k)))
    colof = lambda k: pal[level(plan, k) - plan.base_layers]
    z = np.full(shape, zof(bg))
    col = np.broadcast_to(colof(bg), shape + (3,)).copy()

    def paint(cov, k):
        nonlocal z, col
        z = z * (1 - cov) + zof(k) * cov
        col = col * (1 - cov[..., None]) + colof(k) * cov[..., None]

    if ink == bg:
        warn.append("The text is the same filament as the card; pick another ink.")
    contrast = np.linalg.norm(srgb_to_lab(colof(ink)) - srgb_to_lab(colof(bg)))
    if ink != bg and contrast < 30:
        warn.append(f"Text and card colours are close (dE {contrast:.0f}); it may be hard to read.")

    left, right = MARGIN, W - MARGIN
    if spec.border:
        b = float(spec.border)
        paint(1 - _rect(shape, px, b, b, W - b, H - b), accent)
        left, right = MARGIN + b, W - MARGIN - b

    # QR on the right, on a panel of the lightest filament with the darkest modules
    if spec.qr:
        m = qr_matrix(spec.qr)
        quiet = 2                       # modules; a raised panel edge is a clear border
        side = (len(m) + 2 * quiet) * QR_MODULE
        if side > H - 2 * MARGIN:
            raise ValueError(f"The QR text is too long for a card ({len(spec.qr)} characters); use a shorter link")
        lum = [srgb_to_lab(colof(k))[0] for k in range(n)]
        dark, light = int(np.argmin(lum)), int(np.argmax(lum))
        x0, y0 = right - side, (H - side) / 2
        if light != bg:
            paint(_rect(shape, px, x0, y0, x0 + side, y0 + side), light)
        # which module each pixel centre falls in (hard edges: the squares sit on a 1 mm grid)
        h, w = shape
        r = np.floor(((np.arange(h) + 0.5) * px - y0) / QR_MODULE).astype(int) - quiet
        c = np.floor(((np.arange(w) + 0.5) * px - x0) / QR_MODULE).astype(int) - quiet
        okr, okc = (r >= 0) & (r < len(m)), (c >= 0) & (c < len(m))
        cov = np.zeros(shape)
        cov[np.ix_(okr, okc)] = m[np.ix_(r[okr], c[okc])]
        paint(cov, dark)
        right = x0 - 4.0

    # picture on the left: layered photo or one-colour logo
    if spec.picture is not None:
        side = min(H - 2 * MARGIN, 34.0)
        x0, y0 = left, (H - side) / 2
        pic = spec.picture
        s = min(pic.size)
        pic = pic.crop(((pic.width - s) // 2, (pic.height - s) // 2, (pic.width + s) // 2, (pic.height + s) // 2))
        i0, j0 = round(y0 / px), round(x0 / px)
        size = round(side / px)
        if spec.picture_mode == "logo":
            g = np.asarray(pic.convert("L").resize((size, size), Image.LANCZOS), dtype=np.float64) / 255
            cov = np.zeros(shape)
            cov[i0:i0 + size, j0:j0 + size] = np.clip((0.5 - g) * 8 + 0.5, 0, 1)    # dark = ink, soft edge
            paint(cov, accent)
        else:
            rgb = fit(pic, side, 0.2, detail=0.5)       # photo pixels stay 0.2 mm like the main mode
            hl = despeckle(heights(rgb, plan), 3)
            hl = np.asarray(Image.fromarray(hl.astype(np.uint8)).resize((size, size), Image.NEAREST), dtype=int)
            z[i0:i0 + size, j0:j0 + size] = plan.z_top(hl)
            col[i0:i0 + size, j0:j0 + size] = pal[hl - plan.base_layers]
        left = x0 + side + 4.0

    # text block: name big, the rest smaller, scaled down together to fit
    lines = [t.strip() for t in spec.lines if t and t.strip()]
    if lines:
        ems = [6.0] + [3.6] + [3.2] * (len(lines) - 2) if len(lines) > 1 else [6.0]
        lead = [e * 1.45 for e in ems]
        gap = 3.0 if spec.rule and len(lines) > 1 else 0.0        # room for the rule under the name
        box_w = right - left
        if box_w < 20:
            raise ValueError("No room left for text; leave out the picture or the QR code")
        need_w = max(_width(t, e, px) for t, e in zip(lines, ems))
        need_h = sum(lead) - (lead[0] - ems[0]) * 0.6 + gap
        s = min(1.0, box_w / need_w, (H - 2 * MARGIN) / need_h)
        if min(ems) * s < MIN_EM - 1e-6:
            raise ValueError("The text doesn't fit at a readable size; shorten the longest line "
                             "or leave out the picture or the QR code")
        ems = [e * s for e in ems]
        if spec.engrave and min(ems) * CAP < ENGRAVE_CAP - 1e-6:
            warn.append(f"Text under {ENGRAVE_CAP:g} mm cap height fills in when engraved on a 0.4 mm nozzle; "
                        "use the Smooth (face-down) finish, or fewer, shorter lines.")
        lead = [e * 1.45 for e in ems]
        y = (H - (sum(lead) - (lead[0] - ems[0]) * 0.6 + gap * s)) / 2 + ems[0] * 0.9
        cov = np.zeros(shape)
        for i, (t, e) in enumerate(zip(lines, ems)):
            cov = np.maximum(cov, _text_cov(shape, (left, y), t, e, px))
            if i == 0 and gap:
                paint(_rect(shape, px, left, y + 1.4 * s, left + min(18.0, box_w), y + 1.4 * s + 0.9), accent)
                y += gap * s
            y += lead[i + 1] if i + 1 < len(lead) else 0
        paint(cov, ink)
    return CardResult(plan, z, col, px, warn, spec.corner)


def _shift_extreme(m, k, op):
    """Square erosion (op=np.minimum) or dilation (np.maximum) of a bool mask, k odd."""
    r = k // 2
    out = m.copy()
    for axis in (0, 1):
        src, out = out, out.copy()
        pad = np.pad(src, [(r, r) if a == axis else (0, 0) for a in (0, 1)], constant_values=op is np.minimum)
        n = src.shape[axis]
        for d in range(k):
            out = op(out, pad.take(range(d, d + n), axis=axis))
    return out


def _cross(m, op):
    """One step of a 3 x 3 plus-shaped erosion or dilation."""
    pad = np.pad(m, 1, constant_values=op is np.minimum)
    return op.reduce([m, pad[:-2, 1:-1], pad[2:, 1:-1], pad[1:-1, :-2], pad[1:-1, 2:]])


def _octagon(m, radius, op):
    """Erosion (np.minimum) or dilation (np.maximum) with a near-round octagon of
    `radius` pixels: a square, then a diamond. A square alone would treat diagonal
    strokes as thinner than they are."""
    r = round(radius / 1.707)
    m = _shift_extreme(m, 2 * (radius - r) + 1, op)
    for _ in range(r):
        m = _cross(m, op)
    return m


def _thin_parts(m, radius):
    """Pixels of strokes narrower than 2 * radius + 1: what an opening removes, minus
    the corners it only rounds off (those stay within `radius` of what is left)."""
    kept = _octagon(_octagon(m, radius, np.minimum), radius, np.maximum)
    return m & ~kept & ~_octagon(kept, radius, np.maximum)


def render_svg(svg, px, style_sheet=None, background="#ffffff"):
    """sRGB (h, w, 3) floats of an 85 x 55 mm SVG at `px` mm per pixel, on white.
    Text uses the bundled Inter fonts (Inter, Inter Display) whatever font the SVG asks for."""
    import io
    import re
    import resvg_py
    W, H = CARD_MM
    # resvg refuses mm/cm sizes on the root: size it in pixels, keeping (or adding) the viewBox
    m = re.search(r"<svg\b[^>]*>", svg)
    if m is None:
        raise ValueError("Not an SVG file")
    tag = m.group(0)
    size = {a: re.search(rf'\s{a}="([\d.]+)', tag) for a in ("width", "height")}
    if "viewBox" not in tag and all(size.values()):
        tag = tag.replace("<svg", f'<svg viewBox="0 0 {size["width"].group(1)} {size["height"].group(1)}"', 1)
    tag = re.sub(r'\s(width|height)="[^"]*"', "", tag)
    tag = tag.replace("<svg", f'<svg width="{round(W / px)}" height="{round(H / px)}"', 1)
    svg = svg[:m.start()] + tag + svg[m.end():]
    png = resvg_py.svg_to_bytes(svg_string=svg, width=round(W / px), height=round(H / px), background=background,
                                style_sheet=style_sheet, skip_system_fonts=True, font_dirs=[str(FONT.parent)], font_family="Inter",
                                sans_serif_family="Inter", shape_rendering="geometric_precision")
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.size != (round(W / px), round(H / px)):
        im = im.resize((round(W / px), round(H / px)), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64) / 255


def svg_colours(rgb, min_px=200, merge=8.0):
    """The design's flat fill colours: exact colours covering at least `min_px` pixels,
    merging any closer than `merge` dE. Largest first."""
    q = (rgb * 255).round().astype(np.uint32)
    key = (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]
    # only pixels inside a flat area count: anti-aliased edges repeat their in-between colours too
    flat = np.ones(key.shape, bool)
    flat[1:-1, 1:-1] = ((key[1:-1, 1:-1] == key[:-2, 1:-1]) & (key[1:-1, 1:-1] == key[2:, 1:-1])
                        & (key[1:-1, 1:-1] == key[1:-1, :-2]) & (key[1:-1, 1:-1] == key[1:-1, 2:]))
    keys, counts = np.unique(key[flat], return_counts=True)
    order = np.argsort(-counts)
    cols = []
    for i in order[counts[order] >= min_px]:
        c = np.array([(keys[i] >> 16) & 255, (keys[i] >> 8) & 255, keys[i] & 255]) / 255
        if all(np.linalg.norm(srgb_to_lab(c) - srgb_to_lab(d)) >= merge for d in cols):
            cols.append(c)
    return cols[:8]


def svg_card(svg, stack=None, thickness=0.8, px=0.08, corner=CORNER, back=None, min_stroke=MIN_STROKE, engrave=False):
    """A Card from an 85 x 55 mm SVG layout: every fill colour prints in the nearest
    filament (of `stack`, or of the whole library), raised or sunk to the top of
    that filament's band. The filaments are reordered: the card face first, then
    the others from smallest to largest area, so small text stands lowest (sturdy,
    short shadows, no stripes of other bands on its sides) and big shapes highest.

    back: filament key for the back of the card (the side on the bed), printed
    first under everything; also read from data-back="..." on the <svg> tag.
    Shapes with class="raise" in the top filament stand RAISE layers taller
    (embossed, same colour).

    engrave: the card face goes on top instead, so everything else is cut into it
    (grooves showing the filaments below). Two filaments = one swap. Grooves are
    at least ENGRAVE_STROKE wide, and a warning says when the card colour left
    between them (letter counters, gaps) is thinner than ENGRAVE_RIDGE."""
    import re
    from .filaments import load_library
    if back is None:
        m = re.search(r'<svg\b[^>]*\sdata-back="([^"]+)"', svg)
        back = m.group(1) if m else None
    sub = 2                                           # label at px/2, so edges get 4 coverage levels
    rgb = render_svg(svg, px / sub)
    design = svg_colours(rgb)
    dl = np.stack([srgb_to_lab(c) for c in design])
    q = (rgb * 255).round().astype(np.uint32)
    keys, inv = np.unique(((q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]).ravel(), return_inverse=True)
    lab = srgb_to_lab(np.stack([keys >> 16, (keys >> 8) & 255, keys & 255], -1) / 255)
    label = np.argmin(((lab[:, None, :] - dl) ** 2).sum(-1), axis=-1)[inv].reshape(rgb.shape[:2])
    area = np.bincount(label.ravel(), minlength=len(design))
    cands = pick(stack) if stack else list(load_library().values())
    fl = np.stack([srgb_to_lab(np.array(f.rgb)) for f in cands])
    to_fil = [int(np.argmin(((fl - d) ** 2).sum(-1))) for d in dl]
    warn = []
    used = {}
    for i, k in enumerate(to_fil):
        used[k] = used.get(k, 0) + area[i]
    face = max(used, key=used.get)
    order = [face] + sorted((k for k in used if k != face), key=lambda k: used[k])
    if back:
        keys = [f.key for f in cands]
        if back not in keys:
            raise ValueError(f"The back filament {back!r} is not in the Stack")
        order = [keys.index(back)] + [k for k in order if keys[k] != back]
    if engrave:
        order = order[1:][::-1] + order[:1]           # largest other area lowest, the face on top
    fils, to_fil = [cands[k] for k in order], [order.index(k) for k in to_fil]
    for f in sorted(set(to_fil)):
        same = [design[i] for i in range(len(design)) if to_fil[i] == f]
        if len(same) > 1:
            hexes = ", ".join("#%02X%02X%02X" % tuple(round(v * 255) for v in c) for c in same)
            warn.append(f"Layout colours {hexes} all print in {fils[f].name}; add a filament closer to one of them.")
    lab_fil = np.array(to_fil)[label]                 # filament index per sub-pixel
    face = order.index(face)
    if engrave:
        min_stroke = max(min_stroke, ENGRAVE_STROKE)
    # thicken strokes thinner than one nozzle line (they would vanish or merge in the slicer)
    radius = round((min_stroke / (px / sub) - 1) / 2)          # 2 * radius + 1 pixels ~ min_stroke
    thin_left = 0.0
    for f in sorted(set(to_fil) - {face}):
        for _ in range(4):
            m = lab_fil == f
            thin = _thin_parts(m, radius)
            if thin.sum() < 0.002 * m.sum():
                break
            lab_fil[_cross(thin, np.maximum) & ~m] = f
        thin_left = max(thin_left, thin.sum() / max(1, m.sum()))
    if thin_left >= 0.01:
        warn.append(f"Some lines are still thinner than {min_stroke} mm after thickening; they may not print.")
    if engrave:
        small = [float(m) for m in re.findall(r'<text\b[^>]*\sfont-size="([\d.]+)', svg) if float(m) * CAP < ENGRAVE_CAP - 0.05]
        if small:
            warn.append(f"Text at {min(small) * CAP:.1f} mm cap height is under the {ENGRAVE_CAP:g} mm that engraves cleanly "
                        "on a 0.4 mm nozzle; use the Smooth (face-down) finish or larger text.")
        walls = lab_fil == face
        thin = _thin_parts(walls, round((ENGRAVE_RIDGE / (px / sub) - 1) / 2))
        if thin.sum() > 0.005 * (~walls).sum():         # sharp letter tips alone stay under this
            warn.append(f"The card colour between some grooves is thinner than {ENGRAVE_RIDGE} mm (counters and gaps "
                        "of small text): it will break up. Set text at 5 mm cap height or more, with wider spacing.")
    raise_ = np.zeros(lab_fil.shape, bool)
    if re.search(r'class="[^"]*\braise\b', svg):
        r = render_svg(svg, px / sub, "* { fill: #000; stroke: none } .raise, .raise * { fill: #fff }", "#000000")
        raise_ = r.min(-1) > 0.5
        top = len(fils) - 1
        if (raise_ & (lab_fil != top)).sum() > 0.05 * raise_.sum():
            warn.append(f"Only {fils[top].name} shapes can be raised (it is the top filament); other raised shapes stay flat.")
        raise_ &= lab_fil == top
    plan = card_plan(fils, thickness=thickness, extra=RAISE if raise_.any() else 0)
    pal = plan.palette()
    h, w = lab_fil.shape[0] // sub, lab_fil.shape[1] // sub
    z = np.zeros((h, w))
    col = np.zeros((h, w, 3))
    pool = lambda m: m[:h * sub, :w * sub].reshape(h, sub, w, sub).mean((1, 3))
    for f in set(to_fil) | {face}:
        cov = pool(lab_fil == f)
        z += cov * float(plan.z_top(level(plan, f)))
        col += cov[..., None] * pal[level(plan, f) - plan.base_layers]
    if raise_.any():
        z += pool(raise_) * float(plan.z_top(plan.max_layers) - plan.z_top(plan.max_layers - RAISE))
    return CardResult(plan, z, col, px, warn, corner)


@dataclass
class InlayCard:
    """A Card printed face down, so its front is smooth: the front is the first layers
    on the plate, every colour a flat part side by side (flush, no relief), and the
    body behind them is one filament."""
    filaments: list                   # [body, inlays...]
    labels: np.ndarray                # filament index per pixel, as seen from the front
    depth: float                      # mm of front layers that hold the inlays
    thickness: float                  # mm, the whole card
    px: float
    warnings: list
    corner: float = CORNER

    def inside(self):
        return outline(self.labels.shape, self.px, self.corner) if self.corner else np.ones(self.labels.shape, bool)

    def layers(self):
        """mm per layer, first printed (the front) first."""
        n = round((self.depth - 0.2) / INLAY_LAYER)
        return [0.2] + [INLAY_LAYER] * n

    def front_colours(self):
        """sRGB of each filament seen from the front: an inlay over the body behind it."""
        t = self.layers()
        out = []
        for k in range(len(self.filaments)):
            lay = [0] * 5 + [k] * len(t)                 # viewer side last: body, then the inlay layers
            out.append(stack_colours(lay, self.filaments, np.array([0.08] * 5 + t[::-1]))[-1])
        return np.array(out)

    def preview(self):
        rgb = self.front_colours()[self.labels]
        im = Image.fromarray((rgb * 255).round().astype(np.uint8))
        if self.corner:
            im.putalpha(Image.fromarray((outline(self.labels.shape, self.px, self.corner, True) * 255).round().astype(np.uint8)))
        return im


def inlay_card(card, body_behind=0.4):
    """The flush, face-down version of a raised Card: each pixel takes the filament
    whose band top is nearest its height. The front layers are deep enough for every
    inlay to hide 90% of the body behind it (0.36 to 1.16 mm, in INLAY_LAYER layers),
    and the body behind them is whole layers too."""
    plan, fils = card.plan, card.plan.filaments
    tops = np.array([float(plan.z_top(level(plan, k))) for k in range(len(fils))])
    lab = np.abs(card.z[..., None] - tops).argmin(-1)
    inside = outline(lab.shape, card.px, card.corner) if card.corner else np.ones(lab.shape, bool)
    counts = np.bincount(lab[inside], minlength=len(fils))
    body = int(counts.argmax())
    order = [body] + [k for k in range(len(fils)) if k != body and counts[k]]
    remap = np.zeros(len(fils), int); remap[order] = np.arange(len(order))
    need = max([fils[k].td * TD_SCALE * log(10) for k in order[1:]], default=0.0)
    n = int(np.clip(ceil((need - 0.2) / INLAY_LAYER - 1e-9), 1, 6))
    depth = round(0.2 + INLAY_LAYER * n, 2)
    behind = ceil(body_behind / INLAY_LAYER - 1e-9) * INLAY_LAYER
    return InlayCard([fils[k] for k in order], remap[lab], depth, round(depth + behind, 2), card.px,
                     list(card.warnings), card.corner)


def export_inlay_3mf(out, ic, copies=1, title="business card", name="card.stl", smooth_plate=False):
    """One part per filament, mirrored (the front lies on the plate). The body part is
    its share of the front layers plus the whole card behind them."""
    lab, inside = ic.labels[:, ::-1], ic.inside()[:, ::-1]
    spots = plate_layout(copies)
    parts = []
    for k, f in enumerate(ic.filaments):
        pieces = []
        m = (lab == k) & inside
        if m.any():
            pieces.append(mask_mesh(m, ic.px, 0.0, ic.depth))
        if k == 0:
            pieces.append(mask_mesh(inside, ic.px, ic.depth, ic.thickness))
        vs, fs, n = [], [], 0
        for x, y in spots:
            for v, fc in pieces:
                vs.append(v + [x, -y, 0]); fs.append(fc + n); n += len(v)
        parts.append((np.concatenate(vs), np.concatenate(fs), f))
    write_flat_3mf(out, parts, ic.preview(), title, name=name, layer_height=INLAY_LAYER,
                   bed=SMOOTH_PLATE if smooth_plate else None)
    return sum(len(f) for _, f, _ in parts)


def plate_layout(copies):
    """Card origins (mm) on the A1 bed: 2 columns, up to 4 rows."""
    copies = int(np.clip(copies, 1, 8))
    W, H = CARD_MM
    return [((i % 2) * (W + GAP), (i // 2) * (H + GAP)) for i in range(copies)]


def export_card_3mf(out, card, copies=1, title="business card", name="card.stl"):
    """One card's mesh, repeated on the plate. All copies share the Swap heights."""
    verts, faces = heightfield_mesh(card.z, card.px, max_error=0.4 * card.plan.thickness()[1:].min(), mask=card.mask())
    spots = plate_layout(copies)
    vs, fs = [], []
    for i, (x, y) in enumerate(spots):
        vs.append(verts + [x, -y, 0])
        fs.append(faces + i * len(verts))
    write_3mf(out, np.concatenate(vs), np.concatenate(fs), card.plan, card.preview(), title, name=name)
    return sum(len(f) for f in fs)


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone-card", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lines", nargs="*", help="text lines: name first, then title, phone, email...")
    p.add_argument("--svg", help="an 85 x 55 mm SVG layout instead of text lines: each fill colour prints "
                                 "in the nearest filament of --stack (see examples/cards)")
    p.add_argument("--stack", default="jade_white,blue,black", help="filaments bottom to top")
    p.add_argument("--background", type=int, default=0, help="Stack position of the card face (0 = first)")
    p.add_argument("--ink", type=int, default=-1, help="Stack position of the text (-1 = last)")
    p.add_argument("--accent", type=int, default=1, help="Stack position of the rule, border and logo")
    p.add_argument("--qr", default="", help="link or text for a QR code")
    p.add_argument("--picture", help="photo or logo for the left side")
    p.add_argument("--logo", action="store_true", help="print the picture as a one-colour logo, not a layered photo")
    p.add_argument("--no-rule", action="store_true")
    p.add_argument("--border", type=float, default=0.0, metavar="MM")
    p.add_argument("--copies", type=int, default=8, help="cards on the plate (1-8)")
    p.add_argument("--corner", type=float, default=CORNER, metavar="MM", help="corner radius (0 = square)")
    p.add_argument("--back", help="with --svg: filament for the back of the card (printed first)")
    p.add_argument("--finish", choices=["inlay", "engrave", "relief"], default="inlay",
                   help="inlay: smooth, printed face down, colours flush (default); engrave: face up, text cut into "
                        "the card colour on top (one swap for two filaments); relief: raised text")
    p.add_argument("--relief", action="store_true", help="same as --finish relief")
    p.add_argument("--smooth-plate", action="store_true", help="inlay: print on the smooth PEI plate (glossy, crisper "
                                                                "face) instead of the textured PEI plate")
    p.add_argument("--light-top", action="store_true", help="engrave: keep --background as the face even if it is "
                                                             "light (deeper grooves); by default the darkest filament is")
    p.add_argument("--photo", action="store_true", help="also write <out>_photo.png, a lit, angled render of the printed card")
    p.add_argument("--out", default="card")
    a = p.parse_args(argv)
    finish = "relief" if a.relief else a.finish
    if a.svg:
        card = svg_card(Path(a.svg).read_text(encoding="utf-8"), a.stack.split(","), corner=a.corner, back=a.back,
                        min_stroke=INLAY_STROKE if finish == "inlay" else MIN_STROKE, engrave=finish == "engrave",
                        thickness=0.6 if finish == "engrave" else 0.8)
    elif not a.lines:
        p.error("give text lines or --svg")
    else:
        spec = CardSpec(a.lines, a.stack.split(","), a.background, a.ink, a.accent, a.qr,
                        open_image(a.picture) if a.picture else None, "logo" if a.logo else "photo",
                        not a.no_rule, a.border, corner=a.corner)
        if a.picture and not a.logo and finish != "relief":
            print("  a layered photo needs raised layers: this card prints with relief")
            finish = "relief"
        card = make_card(engraved(spec, not a.light_top) if finish == "engrave" else spec)
    relief = finish != "inlay"
    card = card if relief else inlay_card(card)
    out = Path(a.out)
    card.preview().save(out.with_suffix(".png"))
    if a.photo:
        from .photo import photo
        photo(card, out_w=1600).save(out.with_name(out.name + "_photo.png"))
    if relief:
        tris = export_card_3mf(out.with_suffix(".3mf"), card, a.copies, out.name, out.with_suffix(".stl").name)
    else:
        tris = export_inlay_3mf(out.with_suffix(".3mf"), card, a.copies, out.name, out.with_suffix(".stl").name,
                                a.smooth_plate)
    print(f"wrote {out}.3mf ({a.copies} cards, {tris:,} triangles) and {out}.png")
    if relief:
        print(f"  start in {card.plan.filaments[0].name}, backing {card.plan.backing:.1f} mm")
        for zz, f in zip(card.plan.swap_z(), card.plan.filaments[1:]):
            print(f"  swap to {f.name} at Z {zz:.2f} mm")
    else:
        print(f"  face down, smooth front: the first {card.depth:.2f} mm hold "
              + ", ".join(f.name for f in card.filaments[1:]) + f" inlaid in {card.filaments[0].name}; "
              f"card {card.thickness:.2f} mm")
    for w in card.warnings:
        print("  warning:", w)


if __name__ == "__main__":
    main()
