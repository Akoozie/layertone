"""Desktop stand for a Layertone picture print: a crisp low wedge with a leaning slot.

Prints flat on the bed with no supports (the slot walls lean 12 degrees, the
mouth has a 0.5 mm lead-in). The slot runs end to end, so any print width
fits. Defaults suit the 120 x 90 mm, 2.48 mm thick blue prints.

    python examples/stand/make_stand.py --thick 2.48 --out stand
    python examples/stand/make_stand.py --thick 1.48 --length 133 --lean 10 --depth 40 \
        --h-front 7 --h-back 16 --y-mouth 15 --slot-depth 8 --out portrait_stand   (133 x 199 portrait)
writes stand.stl (and stand.3mf at 0.20 mm layers with --3mf).
Needs: pip install manifold3d trimesh, and layertone itself (the stand code lives in layertone.stand;
`layertone --stand plain` or `layertone-stand` size it from the print automatically)
"""
import argparse
import numpy as np
from layertone.stand import plain, write_stand_3mf


def make(thick=2.48, clearance=0.3, length=120.0, depth=28.0, h_front=5.0, h_back=12.0,
         lean=12.0, y_mouth=14.0, slot_depth=6.0):
    return plain(thick, clearance, length, depth, h_front, h_back, lean, y_mouth, slot_depth)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--thick", type=float, default=2.48, help="print thickness, mm")
    p.add_argument("--clearance", type=float, default=0.3)
    p.add_argument("--length", type=float, default=120.0)
    p.add_argument("--lean", type=float, default=12.0)
    p.add_argument("--depth", type=float, default=28.0, help="front to back, mm; taller prints need more")
    p.add_argument("--h-front", type=float, default=5.0)
    p.add_argument("--h-back", type=float, default=12.0)
    p.add_argument("--y-mouth", type=float, default=14.0, help="slot centre at the top, from the front")
    p.add_argument("--slot-depth", type=float, default=6.0)
    p.add_argument("--filament", default="jade_white", help="library key for the 3MF")
    p.add_argument("--preview", help="PNG for the 3MF thumbnail")
    p.add_argument("--3mf", dest="three_mf", action="store_true", help="also write <out>.3mf, 0.20 mm layers")
    p.add_argument("--out", default="stand")
    a = p.parse_args()
    import trimesh
    m, floor = make(a.thick, a.clearance, a.length, a.depth, a.h_front, a.h_back, a.lean, a.y_mouth, a.slot_depth)
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts)
    tm.export(a.out + ".stl")
    print(f"{a.out}.stl: {len(tm.faces)} triangles, watertight {tm.is_watertight}, "
          f"size {np.round(tm.extents, 2)}, volume {tm.volume / 1000:.1f} cm3, slot floor y={floor[0]:.2f} z={floor[1]:.2f}")
    if a.three_mf:
        write_3mf(a.out + ".3mf", tm, a.filament, a.preview)



def write_3mf(out, tm, filament, preview):
    write_stand_3mf(out, tm.vertices, tm.faces, filament, preview)

if __name__ == "__main__":
    main()
