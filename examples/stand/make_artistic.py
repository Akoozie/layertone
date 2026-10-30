"""Three sculptural stands for a portrait print (132.8 x 199.4 x 1.48 mm).

contour: an off-centre hill of 15 terraces, 2 mm each, like a topographic map (and like the print, built in layers)
wave:    the plain wedge with its top rising and falling in a slow wave
fins:    a row of thin upright fins of different heights, like a sound waveform

All print flat with no supports; the slot (print + 0.3 mm, 8 mm deep (contour 12), leaning back 10 degrees)
runs end to end. Each footprint reaches at least 25 mm behind the slot so the print can't tip it.

    python examples/stand/make_artistic.py contour --out portrait_contour
"""
import argparse
import math
import numpy as np
from manifold3d import CrossSection, Manifold
from layertone.stand import bar, contour, slot

THICK, CLEAR, LEAN, SLOT_DEPTH, LENGTH = 1.48, 0.3, 10.0, 8.0, 133.0


def wave(amp=0.32, waves=1.5):
    body, top_z = bar(LENGTH, 40, 8, 18)
    body = body.refine(12)
    k = 2 * math.pi * waves / LENGTH

    def w(v):
        x, y, z = v
        return (x, y, z * (1 + amp * math.sin(k * x + 0.6)) if z > 1.0 else z)
    body = body.warp(w)
    zf = 2.6
    cut, floor = slot(LENGTH + 40, THICK + CLEAR, LEAN, 13.5 + (40 - zf) * math.tan(math.radians(LEAN)), lambda y: 40, zf, lead=0.5)
    return body - cut, floor


def fins(n=19, fin=4.0, depth=40.0, plate=2.6):
    pitch = (LENGTH - fin) / (n - 1)
    parts = []
    for i in range(n):
        x = -LENGTH / 2 + fin / 2 + i * pitch
        u = x / (LENGTH / 2)
        h = 11 + 11 * math.cos(u * math.pi / 2) ** 2 + 2.5 * math.sin(u * 7.0) ** 2 * (1 - abs(u))
        prof = [(0, 0), (depth, 0)] + [(depth * (1 - j / 24), 0.45 * h + 0.55 * h * (1 - j / 24) ** 0.6) for j in range(25)]
        m = Manifold.extrude(CrossSection([prof]), fin).translate((0, 0, -fin / 2))
        m = m.transform(np.array([[0, 0, 1, x], [1, 0, 0, 0], [0, 1, 0, 0]], float))
        parts.append(m)
    plan = CrossSection.square((LENGTH - 12, depth - 12), center=True).offset(6, circular_segments=96)
    base = Manifold.batch_hull([Manifold.extrude(plan.offset(-0.8, circular_segments=96), 0.01).translate((0, depth / 2, 0)),
                                Manifold.extrude(plan, 0.01).translate((0, depth / 2, 0.8))])
    base = base + Manifold.extrude(plan, plate - 0.8).translate((0, depth / 2, 0.8))
    body = Manifold.batch_boolean(parts + [base], __import__("manifold3d").OpType.Add)
    cut, floor = slot(LENGTH + 40, THICK + CLEAR, LEAN, 13.5 + (40 - plate - 0.4) * math.tan(math.radians(LEAN)), lambda y: 40, plate + 0.4, lead=0.5)
    return body - cut, floor


def main():
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["contour", "wave", "fins"])
    p.add_argument("--out", default=None)
    p.add_argument("--3mf", dest="three_mf", action="store_true")
    p.add_argument("--preview")
    a = p.parse_args()
    import trimesh
    from make_stand import write_3mf
    m, floor = globals()[a.kind]()
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts)
    out = a.out or f"portrait_{a.kind}"
    tm.export(out + ".stl")
    print(f"{out}.stl: {len(tm.faces)} triangles, watertight {tm.is_watertight}, size {np.round(tm.extents, 1)}, "
          f"volume {tm.volume / 1000:.1f} cm3, y {tm.bounds[0][1]:.1f}..{tm.bounds[1][1]:.1f}, slot floor y={floor[0]:.2f} z={floor[1]:.2f}")
    if a.three_mf:
        write_3mf(out + ".3mf", tm, "jade_white", a.preview)


if __name__ == "__main__":
    main()
