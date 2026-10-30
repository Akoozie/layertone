"""layertone-swatch: a calibration print for measuring a filament's real TD,
read by eye (the reference-rail idea from Kromacut's wedge, written fresh).

A row of bars on the base filament: bar k has 2k layers of the top filament.
Bar 0 is bare base and twice as wide; every 5th bar is longer, to count by.
Along the top runs a thick rail of the top filament, as opaque as it gets.
Find the first bar you can't tell apart from the rail, then:

    layertone-swatch --matched 14 --filament jade_white

turns that bar number into a TD and saves it in filaments.json.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image

from .filaments import LIBRARY, pick
from .mesh import write_stl
from .optics import TD_SCALE
from .pipeline import Result, export_3mf
from .plan import Plan

BAR_MM, BAR_LEN_MM, TICK_MM, RAIL_MM, PX = 6.0, 22.0, 4.0, 6.0, 0.2
STEP = 2            # layers of top filament added per bar
RAIL_LAYERS = 50    # 4 mm of top filament: opaque for any TD we expect
HIDDEN = 0.95       # "can't tell apart" ~ the bar hides 95 % of the base


def swatch(base, top, bars=24, base_layers=5):
    plan = Plan([base, top], [base_layers], base_layers, base_layers + RAIL_LAYERS, 0.2, 0.08)
    w, rail, bar, tick = (round(v / PX) for v in (BAR_MM, RAIL_MM, BAR_LEN_MM, TICK_MM))
    n = np.zeros((rail + bar + tick, (bars + 2) * w), dtype=int)
    n[:rail] = base_layers + RAIL_LAYERS
    for k in range(bars + 1):
        x0 = 0 if k == 0 else (k + 1) * w
        x1 = (k + 2) * w
        long = k % 5 == 0
        n[rail:rail + bar + (tick if long else 0), x0:x1] = base_layers + k * STEP
    # the short bars leave a gap under them; fill it with bare base so the panel stays rectangular
    n[n == 0] = base_layers
    return plan, n


def td_from_match(bar, layer_h=0.08):
    """Bar `bar` hides ~95 % of the base: 1 - exp(-t / (TD * TD_SCALE)) = HIDDEN."""
    t = bar * STEP * layer_h
    return round(t / (-np.log(1 - HIDDEN) * TD_SCALE), 2)


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone-swatch", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stack", default="black,jade_white", help="base,top filament keys")
    p.add_argument("--bars", type=int, default=24)
    p.add_argument("--out", default="swatch")
    p.add_argument("--matched", type=int, help="first bar that matches the rail (bar 0 = wide black)")
    p.add_argument("--filament", help="filament key to save the measured TD for")
    a = p.parse_args(argv)

    if a.matched is not None:
        td = td_from_match(a.matched)
        print(f"bar {a.matched} = {a.matched * STEP * 0.08:.2f} mm of filament: TD about {td}")
        if a.filament:
            data = json.loads(LIBRARY.read_text())
            data[a.filament]["td"] = td
            LIBRARY.write_text(json.dumps(data, indent=2) + "\n")
            print(f"saved TD {td} for {a.filament} in {LIBRARY}")
        return

    base, top = pick(a.stack.split(","))
    plan, n = swatch(base, top, a.bars)
    res = Result(plan, 0.0, n)
    out = Path(a.out)
    verts, faces = export_3mf(out.with_suffix(".3mf"), res, PX, f"TD swatch {top.name} on {base.name}",
                              out.with_suffix(".stl").name)
    write_stl(out.with_suffix(".stl"), verts, faces)
    res.preview().resize((n.shape[1] * 2, n.shape[0] * 2), Image.NEAREST).save(out.with_suffix(".png"))
    h, w = n.shape
    print(f"wrote {out}.3mf: {w * PX:.0f} x {h * PX:.0f} mm, bars of 0..{a.bars * STEP} layers of {top.name}, "
          f"rail {RAIL_LAYERS} layers")
    print(f"swap to {top.name} at Z {plan.swap_z()[0]:.2f} mm (already in the 3MF)")
    print("then: find the first bar that matches the rail and run "
          f"layertone-swatch --matched N --filament {top.key}")


if __name__ == "__main__":
    main()
