"""Stacks with more filaments than the AMS lite has slots.

The A1's AMS lite holds 4 spools. A Stack may have up to MAX_STACK filaments,
and a filament may come back later in the Stack (black, white, blue, black).
Each AMS slot is a lane: the printer's tool changes only ever pick a lane.
When the Stack needs a filament that isn't loaded, the print pauses one layer
before that Swap and you swap the spool in one lane for the new one (a Spool
change). The lane emptied is never the one printing, and is the one needed
again furthest in the future, so you swap as few spools as possible.
"""
from dataclasses import dataclass

SLOTS = 4           # AMS lite
MAX_STACK = 8


@dataclass
class SpoolChange:
    position: int       # Stack index of the filament that needs it
    lane: int           # 1-based project filament (AMS lane) whose spool you swap
    out: object         # Filament taken out
    into: object        # Filament put in
    pause_layer: int    # the print pauses before printing this layer (0 = first layer)


@dataclass
class Loading:
    lanes: list         # lane (1-based) for every Stack position
    start: list         # Filament loaded in each lane when the print starts
    changes: list       # [SpoolChange] in print order


def loading(filaments, swaps=None, slots=SLOTS):
    """Which lane every filament of the Stack prints from, and the Spool changes.
    swaps (layer where Stack position j+1 starts) sets each change's pause layer;
    raises ValueError when there is no free layer to pause on."""
    keys = [f.key for f in filaments]
    held = []                     # key per lane
    lanes, start, changes = [], [], []
    for j, f in enumerate(filaments):
        if f.key in held:
            lanes.append(held.index(f.key) + 1)
            continue
        if len(held) < slots:
            held.append(f.key); start.append(f); lanes.append(len(held))
            continue
        # empty the lane needed again furthest away, never the one printing now
        def next_use(k):
            return next((i for i in range(j, len(keys)) if keys[i] == k), len(keys))
        lane = max((i for i, k in enumerate(held) if k != keys[j - 1]), key=lambda i: next_use(held[i]))
        last = max(i for i in range(j) if lanes[i] == lane + 1)
        out = filaments[last]
        held[lane] = f.key
        lanes.append(lane + 1)
        changes.append(SpoolChange(j, lane + 1, out, f, _pause_layer(swaps, last, j) if swaps else -1))
    return Loading(lanes, start, changes)


def _pause_layer(swaps, last, j):
    """The latest layer after the lane's old filament stopped printing (Stack
    position `last`) and before position j starts, that has no tool change."""
    lo, hi = swaps[last], swaps[j - 1]          # position last+1 starts at swaps[last]
    taken = set(swaps)
    for p in range(hi - 1, lo, -1):
        if p not in taken:
            return p
    raise ValueError(f"no layer left to pause on for the spool change before layer {hi}; spread the swaps out")


def check_stack(filaments):
    """A Stack the printer can do: 1..MAX_STACK filaments, the same one never twice in a row."""
    if not 1 <= len(filaments) <= MAX_STACK:
        raise ValueError(f"a Stack has 1 to {MAX_STACK} filaments")
    for a, b in zip(filaments, filaments[1:]):
        if a.key == b.key:
            raise ValueError(f"{a.name} twice in a row: that is one thicker band, not a Swap")


def feasible(filaments, swaps, slots=SLOTS):
    try:
        loading(filaments, swaps, slots)
        return True
    except ValueError:
        return False


def pause_z(plan, change):
    """top_z of the layer the print pauses before (as Bambu Studio shows it)."""
    return round(float(plan.z_top(change.pause_layer + 1)), 2)


def describe(plan):
    """One line per Spool change, for the CLI and the 3MF description."""
    ld = loading(plan.filaments, plan.swaps)
    return [f"pause at Z {pause_z(plan, c):.2f} mm: swap the {c.out.name} spool for {c.into.name}"
            for c in ld.changes]
