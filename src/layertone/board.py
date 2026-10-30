"""layertone-board: a calibration board for one Stack and Swap plan.

One tile for every printable Height, in order, plus a chart of the colours
the app expects for each tile. Print the board, hold it next to the chart:
where a printed tile is lighter or darker than its chart tile, the TD of the
filament on top there is off (lighter print = real TD higher than the guess).
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

from .filaments import pick
from .pipeline import Result, export_3mf
from .plan import Plan

TILE_MM, GAP_MM, COLS, PX = 8.0, 1.0, 6, 0.2


def board(filaments, swaps=None, base_layers=5, max_layers=17):
    """Plan and Heights for the board. Without swaps, spread them evenly."""
    if swaps is None:
        n = len(filaments) - 1
        swaps = [base_layers + round(i * (max_layers - base_layers) / (n + 1)) for i in range(n)]
    plan = Plan(filaments, list(swaps), base_layers, max_layers, 0.2, 0.08)
    levels = list(range(base_layers + 1, max_layers + 1))      # the background is the base itself
    rows = -(-len(levels) // COLS)
    t, g = round(TILE_MM / PX), round(GAP_MM / PX)
    heights = np.full((rows * (t + g) + g, COLS * (t + g) + g), base_layers)
    for i, lv in enumerate(levels):
        r, c = divmod(i, COLS)
        heights[g + r * (t + g):g + r * (t + g) + t, g + c * (t + g):g + c * (t + g) + t] = lv
    return Result(plan, 0.0, heights), levels


def chart(result, levels, scale=4):
    """The expected colours as a picture, each tile numbered with its Height and Z."""
    plan = result.plan
    img = result.preview().resize((result.heights.shape[1] * scale, result.heights.shape[0] * scale), Image.NEAREST)
    d = ImageDraw.Draw(img)
    t, g = round(TILE_MM / PX) * scale, round(GAP_MM / PX) * scale
    pal = plan.palette()
    for i, lv in enumerate(levels):
        r, c = divmod(i, COLS)
        x, y = g + c * (t + g), g + r * (t + g)
        light = pal[lv - plan.base_layers].mean() > 0.5
        d.text((x + 6, y + 6), f"{lv}\n{plan.z_top(lv):.2f} mm", fill=(0, 0, 0) if light else (255, 255, 255), font_size=22)
    light = pal[0].mean() > 0.5
    d.text((g, img.height - g + 4), f"background = base, {plan.base_layers} layers", fill=(0, 0, 0) if light else (255, 255, 255),
           font_size=18)
    return img


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone-board", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stack", default="black,jade_white")
    p.add_argument("--swaps", help="swap layers, e.g. 5,9 (default: spread evenly)")
    p.add_argument("--base-layers", type=int, default=5)
    p.add_argument("--max-layers", type=int, default=17)
    p.add_argument("--out", default="board")
    a = p.parse_args(argv)
    fils = pick(a.stack.split(","))
    res, levels = board(fils, [int(x) for x in a.swaps.split(",")] if a.swaps else None, a.base_layers, a.max_layers)
    out = Path(a.out)
    export_3mf(out.with_suffix(".3mf"), res, PX, out.name, out.with_suffix(".stl").name)
    chart(res, levels).save(out.with_suffix(".png"))
    h, w = res.heights.shape
    print(f"wrote {out}.3mf and {out}.png (the chart): {w * PX:.0f} x {h * PX:.0f} mm, {len(levels)} tiles")
    for zz, f in zip(res.plan.swap_z(), fils[1:]):
        print(f"  swap to {f.name} at Z {zz:.2f} mm")


if __name__ == "__main__":
    main()
