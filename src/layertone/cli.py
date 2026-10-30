"""layertone: image -> layered filament relief (STL + preview + Bambu 3MF)."""
import argparse
from pathlib import Path
from PIL import Image
import numpy as np

from .mesh import write_stl
from .pipeline import FRAME_STYLES, export_3mf, export_flat_3mf, fit, flat_paint, open_image, render


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone", description=__doc__)
    p.add_argument("image")
    p.add_argument("--stack", default="black,jade_white",
                   help="filaments bottom to top, comma separated (see filaments.json). Up to 8, and one may come "
                        "back later (black,jade_white,blue,black); past the 4 AMS slots the print pauses for a spool change")
    p.add_argument("--width", type=float, default=100.0, help="print width in mm")
    p.add_argument("--px", type=float, default=0.2, help="mm per pixel")
    p.add_argument("--base-layers", type=int, default=5, help="layers every pixel gets (5 = 0.52 mm)")
    p.add_argument("--max-layers", type=int, default=17, help="tallest pixel in layers (17 = 1.48 mm)")
    p.add_argument("--backing", type=float, default=1.0, metavar="MM",
                   help="solid first filament under the picture so it isn't paper-thin (0.2 mm steps; 0 = off)")
    p.add_argument("--frame", type=float, default=0, metavar="MM",
                   help="raised border this wide around the picture, as tall as the tallest point (0 = off)")
    p.add_argument("--frame-style", choices=FRAME_STYLES, default="flat",
                   help="style of the raised border (flat, dark, bevel, cove, steps, mat, double, lip, beads, rounded)")
    p.add_argument("--corner", type=float, default=0, metavar="MM",
                   help="round the print's corners with this radius, e.g. 3 for a trading card at 63 mm wide (0 = square)")
    p.add_argument("--crop", type=int, nargs=4, metavar=("L", "T", "R", "B"))
    p.add_argument("--detail", type=float, default=0.0,
                   help="0..1, boost local contrast and sharpen before mapping (1 = strong)")
    p.add_argument("--brightness", type=float, default=0.0, help="-1..1, lift (+) or darken (-) mid-tones")
    p.add_argument("--contrast", type=float, default=1.0, help="0.5..2, 1 = unchanged")
    p.add_argument("--smooth", type=float, default=0, metavar="MM",
                   help="median-filter grain and print dots up to this size first (0 = off)")
    p.add_argument("--colours", type=int, default=0, help="reduce the picture to this many colours first (0 = off)")
    p.add_argument("--speck", type=float, default=0.6, metavar="MM",
                   help="remove height specks smaller than this (0.6 = lone pixels, 0 = off)")
    p.add_argument("--dither", type=float, default=0, metavar="MM",
                   help="dither between layers in dots of this size (0.4 = one nozzle line; 0 = off)")
    p.add_argument("--swaps", help="set the swap layers by hand, e.g. 5,9 (layer 0 = first layer)")
    p.add_argument("--thin", type=int, default=0,
                   help="make this many layers after the first swap 0.04 mm (more shadow tones)")
    p.add_argument("--restore-faces", action="store_true",
                   help="sharpen faces with GFPGAN first (needs pip install layertone[faces])")
    p.add_argument("--flat", type=float, default=0, metavar="MM",
                   help="Flat Paint: flat pieces this tall, each colour its own filament (no layered blending)")
    p.add_argument("--suggest", action="store_true",
                   help="only list the filaments that would most improve this picture, then stop")
    p.add_argument("--suggest-set", action="store_true",
                   help="ignore --stack: list the best 2, 3 and 4 filaments to buy and load for this picture, then stop")
    p.add_argument("--most", type=int, default=4,
                   help="with --suggest-set: biggest Stack to try (up to 8; past 4 means spool changes)")
    p.add_argument("--stand", choices=["none", "plain", "contour"], default="none",
                   help="also write <out>_stand.stl/.3mf, a desk stand sized to the print (plain wedge or contour hill)")
    p.add_argument("--stand-filament", default="jade_white", help="filament for the stand's 3MF")
    p.add_argument("--wall", metavar="COLSxROWS",
                   help="split into tiles that fit the A1 bed, all with the same swaps: 'auto' or e.g. 2x2 "
                        "(set the whole wall's size with --width)")
    p.add_argument("--join", choices=["magnets", "keys", "plates", "none"], default="magnets",
                   help="how wall tiles join on the back: 5 x 2 mm magnets + links, butterfly keys, "
                        "peg plates, or none (glue onto a board)")
    p.add_argument("--out", help="output name without extension (default: <image>_layertone)")
    p.add_argument("--title", default=None)
    a = p.parse_args(argv)

    from .spools import check_stack
    from .suggest import stack_filaments
    try:
        fils = stack_filaments(a.stack.split(","))      # your library, then the catalogue (to try before buying)
        check_stack(fils)
    except ValueError as e:
        raise SystemExit(str(e))
    img = open_image(a.image)
    if a.restore_faces:
        from .faces import restore_faces
        img = restore_faces(img)
    rgb = fit(img, a.width, a.px, a.crop, a.detail, a.brightness, a.contrast, a.smooth, a.colours)
    if a.suggest_set:
        from .suggest import describe_sets, suggest_set
        for line in describe_sets(suggest_set(rgb, a.base_layers, a.max_layers, most=a.most)):
            print(line)
        return
    if a.suggest:
        from .suggest import suggest
        now, found = suggest(rgb, fils, a.base_layers, a.max_layers)
        print(f"colour error now {now:.2f}")
        for e, f, owned, pos in found:
            where = "at the bottom" if pos == 0 else f"after {fils[pos - 1].name}"
            print(f"  {e:.2f}  add {f.name} {where}{'  (in your list)' if owned else ''}")
        if not found:
            print("  no single filament makes it better")
        return
    if a.flat:
        out = Path(a.out or Path(a.image).with_suffix("").as_posix() + "_flat")
        res = flat_paint(rgb, fils, base_layers=0, paint_layers=max(1, round((a.flat - 0.2) / 0.08) + 1),
                         speck=2 * round(a.speck / a.px / 2) + 1 if a.speck else 1)
        parts = export_flat_3mf(out.with_suffix(".3mf"), res, a.px, a.title or out.name, out.with_suffix(".stl").name)
        prev = res.preview()
        prev.resize((prev.width * 2, prev.height * 2), Image.NEAREST).save(out.with_suffix(".png"))
        print(f"wrote {out}.png/.3mf  Flat Paint, {res.top_z:.2f} mm tall, mean colour error dE {res.error(rgb):.1f}")
        for v, f, fil in parts:
            print(f"  {fil.name} (slot {fil.slot}): {len(f)} triangles")
        h, w = res.labels.shape
        _stand(a, out, w * a.px, h * a.px, res.top_z)
        return
    if a.wall:
        from .wall import wall_backing
        a.backing = wall_backing(a.backing, a.join)
    res = render(rgb, fils, a.base_layers, a.max_layers, clean=2 * round(a.speck / a.px / 2) + 1 if a.speck else 0,
                 thin=a.thin,
                 dither_block=round(a.dither / a.px) if a.dither else 0,
                 swaps=[int(x) for x in a.swaps.split(",")] if a.swaps else None,
                 backing=a.backing, frame=round(a.frame / a.px), frame_style=a.frame_style, px=a.px)
    plan, err, z = res.plan, res.error, res.z()

    corner = a.corner or res.corner

    out = Path(a.out or Path(a.image).with_suffix("").as_posix() + "_layertone")
    if a.wall:
        _wall(a, res, out, fils, corner=corner)
        return
    mask = None
    if corner:
        from .card import outline
        mask = outline(z.shape, a.px, corner)
    verts, faces = export_3mf(out.with_suffix(".3mf"), res, a.px,
                              a.title or out.name, out.with_suffix(".stl").name, mask=mask)
    write_stl(out.with_suffix(".stl"), verts, faces)
    prev = res.preview()
    if mask is not None:
        prev = Image.fromarray(np.where(mask[..., None], np.asarray(prev), 0).astype(np.uint8))
    prev.resize((prev.width * 2, prev.height * 2), Image.NEAREST).save(out.with_suffix(".png"))

    h, w = z.shape
    print(f"wrote {out}.stl/.png/.3mf  {w * a.px:.1f} x {h * a.px:.1f} mm, "
          f"top {z.max():.2f} mm, {len(faces)} triangles, mean colour error dE {err:.1f}")
    for line in print_plan(plan):
        print(line)
    if plan.backing_range():
        lo, hi = plan.backing_range()
        print(f"backing layers from {lo:.2f} to {hi:.2f} mm are 0.2 mm (set in the 3MF)")
    if plan.thin_range():
        lo, hi = plan.thin_range()
        print(f"layers from {lo:.2f} to {hi:.2f} mm are {plan.thin_h:g} mm (set in the 3MF)")
    _stand(a, out, w * a.px, h * a.px, float(z.max()))


def print_plan(plan):
    """Start, Swaps and Spool changes in print order."""
    from .spools import loading, pause_z
    ld = loading(plan.filaments, plan.swaps)
    fils = plan.filaments
    if ld.changes:
        lines = ["load the AMS lite with: " + ", ".join(f.name for f in ld.start)]
    else:
        lines = []
    slot = (lambda f: "") if ld.changes else (lambda f: f" (slot {f.slot})")    # with spool changes, slots move
    steps = [(z, f"  swap to {f.name}{slot(f)} at Z {z:.2f} mm") for z, f in zip(plan.swap_z(), fils[1:])]
    steps += [(pause_z(plan, c), f"  PAUSE at Z {pause_z(plan, c):.2f} mm: take out {c.out.name}, "
                                 f"put {c.into.name} in its slot, resume") for c in ld.changes]
    return lines + [f"start in {fils[0].name}{slot(fils[0])}"] + [t for _, t in sorted(steps)]


def _wall(a, res, out, fils, corner=0.0):
    from .wall import export_wall, grid
    h, w = res.heights.shape
    cols, rows = (0, 0) if a.wall == "auto" else (int(v) for v in a.wall.lower().split("x"))
    cols, rows = grid((w - 1) * a.px, (h - 1) * a.px, cols, rows)
    mask = None
    if corner:
        from .card import outline
        mask = outline(res.heights.shape, a.px, corner)
    files, _ = export_wall(out.parent, res, a.px, cols, rows, a.join, out.name, mask=mask)
    plan = res.plan
    print(f"wall {(w - 1) * a.px:.0f} x {(h - 1) * a.px:.0f} mm as {cols} x {rows} tiles, "
          f"{float(res.z().max()):.2f} mm thick ({plan.backing:.1f} mm backing for the {a.join} joins), "
          f"mean colour error dE {res.error:.1f}")
    print("every tile:")
    for line in print_plan(plan):
        print(line)
    for name, note in files:
        print(f"  wrote {out.parent / name}  {note}")


def _stand(a, out, width, height, thick):
    if a.stand == "none":
        return
    from .stand import describe, export_stand
    base = out.with_name(out.name + "_stand")
    verts, faces = export_stand(base, width, height, thick, a.stand, a.stand_filament)
    print(f"wrote {base}.stl/.3mf  {a.stand} stand, {describe(verts)}, slot {thick + 0.3:.2f} mm, "
          f"{a.stand_filament}, 0.20 mm layers")


if __name__ == "__main__":
    main()
