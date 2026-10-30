"""Desktop stands for a picture print, sized from the print: a separate single-colour part.

plain:   a crisp low wedge with a slot leaning back, as long as the print is wide
contour: an off-centre hill of 15 terraces, 2 mm each, with the slot on the summit

Both print flat with no supports. The slot is the print's thickness + 0.3 mm and runs end to end.
Sizes come from two tuned stands (120 x 90 x 2.48 mm blue prints and the 133 x 199 x 1.48 mm portrait),
blended by print height: taller prints get a deeper, taller bar, a gentler lean and a deeper slot,
so their weight stays over the footprint.

    layertone-stand --width 133 --height 199.4 --thick 1.48 --style contour --out portrait_stand
"""
import argparse
import math
from pathlib import Path

import numpy as np

STYLES = ("none", "plain", "contour")
CLEARANCE = 0.3
# plain wedge settings for a 90 mm and a 199.4 mm tall print: depth, h_front, h_back, lean, y_mouth, slot_depth
_LOW, _HIGH = (89.8, (28, 5, 12, 12, 14, 6)), (199.4, (40, 7, 16, 10, 15, 8))
BED_MM = 250.0


def _m():
    try:
        import manifold3d
    except ImportError:
        raise ValueError("Stands need manifold3d: pip install manifold3d") from None
    return manifold3d


def bar(length, depth, h_front, h_back, corner=6.0, edge=1.5, foot=0.8, front_lean=8.0):
    """Crisp wedge: front face leaning back, top sloping up to a sharp back edge, one front chamfer."""
    m3 = _m()
    CrossSection, Manifold = m3.CrossSection, m3.Manifold

    def top_z(y):
        return h_front + (h_back - h_front) * y / depth
    yf = h_front * math.tan(math.radians(front_lean))          # front face top, set back
    side = [(0, 0), (depth, 0), (depth, h_back), (yf + edge, top_z(yf + edge)), (yf, h_front - edge)]
    prof = Manifold.extrude(CrossSection([side]), length).translate((0, 0, -length / 2))
    prof = prof.transform(np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], float))
    plan = CrossSection.square((length - 2 * corner, depth - 2 * corner), center=True).offset(corner, circular_segments=96)
    tall = Manifold.extrude(plan, h_back + 5).translate((0, depth / 2, foot))
    chamf = Manifold.batch_hull([Manifold.extrude(plan.offset(-foot, circular_segments=96), 0.01).translate((0, depth / 2, 0)),
                                 Manifold.extrude(plan, 0.01).translate((0, depth / 2, foot))])
    return prof ^ (tall + chamf), top_z


def slot(length, width, lean_deg, y_mouth, top_z, floor_z, lead=0.5):
    """Slot leaning back by lean_deg, centred at y_mouth where it meets the top, floor at floor_z."""
    m3 = _m()
    t = math.radians(lean_deg)
    u = np.array([math.sin(t), math.cos(t)])        # up the slot, in (y, z)
    n = np.array([math.cos(t), -math.sin(t)])       # across it
    zm = top_z(y_mouth)
    run = (zm - floor_z) / math.cos(t)              # floor to mouth along the slot
    f = np.array([y_mouth, zm]) - u * run
    w = width / 2
    s = run - lead                                  # 45 degree lead-in from here up
    k = lead + 10
    poly = [f - n * w, f + u * s - n * w, f + u * (s + k) - n * (w + k),
            f + u * (s + k) + n * (w + k), f + u * s + n * w, f + n * w]
    cs = m3.CrossSection([[tuple(p) for p in poly[::-1]]])
    m = m3.Manifold.extrude(cs, length + 40).translate((0, 0, -(length + 40) / 2))
    # extrusion axis -> x, 2D (y, z) -> (y, z)
    return m.transform(np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]], float)), f


def plain(thick=2.48, clearance=CLEARANCE, length=120.0, depth=28.0, h_front=5.0, h_back=12.0,
          lean=12.0, y_mouth=14.0, slot_depth=6.0):
    body, top_z = bar(length, depth, h_front, h_back)
    cut, floor = slot(length, thick + clearance, lean, y_mouth, top_z, top_z(y_mouth) - slot_depth)
    return body - cut, floor


def _blob(a, b, yc, phase, wob=1.0, n=240):
    """Superellipse with a slow wobble, as a CrossSection."""
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        c, s = math.cos(t), math.sin(t)
        r = 1 + wob * (0.035 * math.sin(2 * t + phase) + 0.025 * math.sin(3 * t + 1.7 * phase) + 0.015 * math.sin(5 * t - phase))
        e = 2.6
        x = a * r * math.copysign(abs(c) ** (2 / e), c)
        y = yc + b * r * math.copysign(abs(s) ** (2 / e), s)
        pts.append((x, y))
    return _m().CrossSection([pts])


def contour(thick=1.48, clearance=CLEARANCE, sx=1.0, sy=1.0, lean=10.0, levels=15, step=2.0, y_slot=50.0,
            slot_depth=12.0):
    """An off-centre hill: the terraces spread wide to the right and front and bunch up on the left.
    The slot sits on the summit, so the picture grows out of the terrain. sx, sy scale the footprint
    (1, 1 = 195 x 86 mm, made for the 133 x 199 mm portrait print)."""
    Manifold = _m().Manifold
    body, prev = None, None
    for k in range(levels):
        f = k / (levels - 1)
        g = f ** 0.8                                   # uneven steps: wide low down, tight near the top
        a = (95 - 38 * g) * sx                         # half width: 190 mm at the bottom, 114 at the summit
        front, back = (52 - 45 * g) * sy, (33 - 26 * g) * sy   # reach in front of / behind the slot
        x0 = 22 * (1 - g) * sx                         # the hill's foot reaches out to the right
        cs = _blob(a, (front + back) / 2, y_slot + (back - front) / 2, phase=0.9 * k, wob=1.5 + 0.8 * f).translate((x0, 0))
        if prev is not None:
            cs = cs ^ prev.offset(-1.2, circular_segments=48)
        layer = Manifold.extrude(cs, step + (0.05 if k < levels - 1 else 0)).translate((0, 0, k * step))
        body = layer if body is None else body + layer
        prev = cs
    top = levels * step
    cut, floor = slot(133.0 * sx + 120, thick + clearance, lean, y_slot, lambda y: top, top - slot_depth, lead=0.5)
    return (body - cut).simplify(0.01), floor          # simplify drops near-duplicate points left by the offsets


def plain_settings(width, height, thick):
    """The plain wedge's sizes for a print, blended between the two tuned stands by print height."""
    (h0, lo), (h1, hi) = _LOW, _HIGH
    t = min(max((height - h0) / (h1 - h0), 0.0), 1.5)
    depth, h_front, h_back, lean, y_mouth, slot_depth = (float(round(a + t * (b - a))) for a, b in zip(lo, hi))
    return dict(thick=thick, length=float(round(width)), depth=depth, h_front=h_front, h_back=h_back,
                lean=lean, y_mouth=y_mouth, slot_depth=slot_depth)


def contour_settings(width, height, thick):
    """Footprint scaled from the portrait stand (133 x 199 mm print), kept on the bed."""
    sx = min(round(width) / 133.0, BED_MM / 195.1)
    sy = min(max(round(height) / 199.0, 0.75), 1.3)   # 0.75 keeps the summit ~10 mm deep round the slot
    return dict(thick=thick, sx=sx, sy=sy)


def stand_size(width, height, thick, style="plain"):
    """Approximate outside size (x, y, z mm) without building the mesh, for the page."""
    if style == "plain":
        p = plain_settings(width, height, thick)
        return [p["length"], p["depth"], p["h_back"]]
    p = contour_settings(width, height, thick)
    return [round(195.1 * p["sx"]), round(85.6 * p["sy"]), 30.0]


def make_stand(width, height, thick, style="plain"):
    """(verts, faces) of a stand for a width x height mm print, thick mm thick, standing on the bed at z=0."""
    if style not in ("plain", "contour"):
        raise ValueError(f"Unknown stand style {style!r}: use plain or contour")
    m, _ = plain(**plain_settings(width, height, thick)) if style == "plain" else contour(**contour_settings(width, height, thick))
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties[:, :3], float), np.asarray(mesh.tri_verts, np.int64)


def describe(verts):
    ext = verts.max(0) - verts.min(0)
    return f"{ext[0]:.0f} x {ext[1]:.0f} x {ext[2]:.0f} mm"


# Bambu settings for a solid part (the template is tuned for 0.08 mm picture layers)
SOLID = {"initial_layer_print_height": "0.2", "wall_loops": "4", "sparse_infill_density": "25%",
         "sparse_infill_pattern": "gyroid", "top_shell_layers": "5", "bottom_shell_layers": "4",
         "enable_support": "0", "curr_bed_type": "Textured PEI Plate"}


def write_stand_3mf(out, verts, faces, filament="jade_white", preview=None, title="Layertone stand"):
    """Bambu 3MF from the Layertone template, retuned for a solid part: 0.20 mm layers, 4 walls, 25% gyroid."""
    from PIL import Image
    from .filaments import pick
    from .threemf import write_flat_3mf
    fil = pick([filament])[0]
    img = Image.open(preview).convert("RGB") if preview else Image.new("RGB", (512, 512), fil.hex)
    write_flat_3mf(out, [(verts, faces, fil)], img, title, name="layertone_stand.stl", layer_height=0.2, extra=SOLID)


def export_stand(out, width, height, thick, style="plain", filament="jade_white", stl=True):
    """Write <out>.3mf (and <out>.stl). Returns (verts, faces)."""
    from .mesh import write_stl
    out = Path(out)
    verts, faces = make_stand(width, height, thick, style)
    write_stand_3mf(out.with_suffix(".3mf"), verts, faces, filament, title=f"{out.name} ({style} stand)")
    if stl:
        write_stl(out.with_suffix(".stl"), verts, faces)
    return verts, faces


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone-stand", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--width", type=float, required=True, help="print width, mm")
    p.add_argument("--height", type=float, required=True, help="print height, mm")
    p.add_argument("--thick", type=float, required=True, help="print thickness (its tallest point), mm")
    p.add_argument("--style", choices=STYLES[1:], default="plain")
    p.add_argument("--filament", default="jade_white", help="library key for the 3MF")
    p.add_argument("--out", default="stand")
    a = p.parse_args(argv)
    verts, faces = export_stand(a.out, a.width, a.height, a.thick, a.style, a.filament)
    print(f"wrote {a.out}.stl/.3mf  {a.style} stand, {describe(verts)}, {len(faces)} triangles")


if __name__ == "__main__":
    main()
