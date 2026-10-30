"""Writes the example card layouts (85 x 55 mm SVGs) in this folder.

Colours are the library filaments' hex values, so each fill maps straight to
Jade White, eSUN blue or black. Text strokes are thickened like Card mode does
(stroke = 0.45 mm minus the face's thinnest stroke), so what you see is what prints.
Edit the text below (or the SVGs in Inkscape) and run: layertone-card --svg file.svg

Grid: 6 mm margins, type on a 4 mm baseline grid, two sizes per card at most.
"""
import base64
import io
from pathlib import Path
import numpy as np
from PIL import Image

WHITE, BLUE, BLACK = "#FFFFFF", "#054795", "#161616"
NAME, ROLE = "Alex Doe", "Layered prints & 3D design"
PHONE, MAIL, WEB = "+31 6 1234 5678", "alex@example.com", "example.com"
M = 6.0                                 # margin, mm
STROKE = 0.42                           # mm, thinnest line Card mode prints flush (INLAY_STROKE)
# thinnest stroke of each face as a share of the em (horizontal bars of e, a, t)
THIN = {("Inter Display", 300): 0.058, ("Inter Display", 400): 0.072, ("Inter Display", 500): 0.083,
        ("Inter Display", 600): 0.098, ("Inter Display", 700): 0.113, ("Inter", 600): 0.098, ("Inter", 700): 0.113}


def text(x, y, s, em, fill, family="Inter", weight=600, track=0.0, anchor="start", cls=""):
    stroke = max(0.0, STROKE - THIN[family, weight] * em)
    c = f' class="{cls}"' if cls else ""
    s = s.replace("&", "&amp;")
    return (f'<text{c} x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-weight="{weight}" font-size="{em}" '
            f'fill="{fill}" stroke="{fill}" stroke-width="{stroke:.3f}" stroke-linejoin="round" '
            f'letter-spacing="{track * em:.3f}" text-anchor="{anchor}">{s}</text>')


def svg(body, face, back=None):
    b = f' data-back="{back}"' if back else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="55mm" viewBox="0 0 85 55"{b}>\n'
            f'<rect width="85" height="55" fill="{face}"/>\n' + "\n".join(body) + "\n</svg>\n")


def crop():
    """White card. A huge blue 'doe' (Inter Display Medium, thin enough to read as a
    mark, not a slab) runs off the bottom edge, its a on the left margin. Everything else
    is one black block on the 4 mm grid above it: name in tracked capitals, role, then
    the details. Blue is only the mark (blue small text would stand on the black band
    and show black on its sides)."""
    rows = [(10, "ALEX DOE", BLACK, 0.10), (14, ROLE, BLACK, 0), (22, MAIL, BLACK, 0), (26, PHONE, BLACK, 0)]
    return svg([text(M, y, s, 2.6, c, track=t) for y, s, c, t in rows] + [
        text(M - 1.75, 63, "doe", 36, BLUE, "Inter Display", 500, -0.035),     # bowl of the a on the margin
    ], WHITE)


def night():
    """Black card, white type set flush. The name large in Inter Display Light (its
    strokes clear the line limit from 7.8 mm up), the details at 3 mm in Inter SemiBold:
    a bit larger than usual, because the fixed 0.42 mm line is then a smaller share of
    the letter and the text reads lighter. Two columns on the same two baselines."""
    em = 3.0
    return svg([
        text(M - 0.3, 17, NAME, 8.4, WHITE, "Inter Display", 300, -0.02),
        text(M, 44.5, "LAYERED PRINTS", em, WHITE, track=0.06),
        text(M, 49, "& 3D DESIGN", em, WHITE, track=0.06),
        text(85 - M, 44.5, MAIL, em, WHITE, track=0.01, anchor="end"),
        text(85 - M, 49, PHONE, em, WHITE, track=0.01, anchor="end"),
    ], BLACK)


def day():
    """Night inverted for the one-swap engraved finish: a white card with the text cut
    through the white top down to black. Grooves are kept 0.45 mm or wider."""
    return night().replace(BLACK, "SWAP").replace(WHITE, BLACK).replace("SWAP", WHITE)


def _image(mask, fill_black=True):
    """An 85 x 55 mm bool mask (True = cut) as an embedded black-on-transparent PNG."""
    a = (mask * 255).astype(np.uint8)
    im = Image.merge("LA", (Image.new("L", a.shape[::-1], 0x16), Image.fromarray(a)))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return (f'<image x="0" y="0" width="85" height="55" preserveAspectRatio="none" '
            f'href="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"/>')


def _grid(px=0.04):
    ys, xs = np.mgrid[0:55:px, 0:85:px]
    return xs + px / 2, ys + px / 2, px


def contour():
    """White card, engraved contour lines of one hill rising off the top right corner,
    like a height map (which is what a print is). Lines 0.55 mm on an even 1.7 mm pitch."""
    x, y, px = _grid()
    dx, dy = x - 80, y - 6
    a = np.arctan2(dy, dx)
    r = np.hypot(dx * 0.82, dy) * (1 + 0.10 * np.sin(3 * a + 0.6) + 0.05 * np.sin(5 * a + 2.1))
    pitch, w = 1.7, 0.55
    gy, gx = np.gradient(r, px)
    d = np.abs((r / pitch + 0.5) % 1 - 0.5) * pitch / (np.hypot(gx, gy) + 1e-9)
    lines = (d < w / 2) & (r > 3 * pitch - w) & (r < 23.5 * pitch)       # an open peak, the last ring whole
    return svg([_image(lines),
                text(M - 0.3, 36, NAME, 7.2, BLACK, "Inter Display", 600, -0.025),
                text(M, 42, "LAYERED PRINTS · 3D DESIGN", 2.8, BLACK, track=0.1),
                text(M, 49, MAIL, 2.8, BLACK, track=0.02)], WHITE)


def monogram():
    """White card with a huge engraved AK running off the left and bottom edges; the
    name and details small and quiet, set right in the top right."""
    return svg([
        text(-3.5, 66, "AD", 52, BLACK, "Inter Display", 700, -0.06),
        text(85 - M, 10, NAME.upper(), 3.0, BLACK, track=0.12, anchor="end"),
        text(85 - M, 14.5, ROLE, 3.0, BLACK, anchor="end"),
        text(85 - M, 22, MAIL, 3.0, BLACK, anchor="end"),
        text(85 - M, 26.5, PHONE, 3.0, BLACK, anchor="end"),
    ], WHITE)


def layers():
    """White card. On the right, engraved horizontal lines that thicken from 0.45 mm at
    the top to 2.6 mm at the bottom on a 3.2 mm pitch, a tone ramp made of layer lines."""
    rows = []
    n = 17
    for i in range(n):
        w = 0.45 + (2.6 - 0.45) * i / (n - 1)
        yc = 0.8 + i * 3.2 + 1.3
        rows.append(f'<rect x="47" y="{yc - w / 2:.3f}" width="40" height="{w:.3f}" fill="{BLACK}"/>')
    return svg(rows + [
        text(M - 0.3, 17, "Alex", 8.4, BLACK, "Inter Display", 300, -0.02),
        text(M - 0.3, 26.5, "Doe", 8.4, BLACK, "Inter Display", 300, -0.02),
        text(M, 44.5, "LAYERED PRINTS", 3.0, BLACK, track=0.06),
        text(M, 49, MAIL, 3.0, BLACK, track=0.01),
    ], WHITE)


if __name__ == "__main__":
    here = Path(__file__).parent
    for name, f in [("crop", crop), ("night", night), ("day", day), ("contour", contour), ("monogram", monogram), ("layers", layers)]:
        (here / f"{name}.svg").write_text(f(), encoding="utf-8")
        print("wrote", name + ".svg")
