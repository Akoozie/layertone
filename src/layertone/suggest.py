"""Filament suggestions.

suggest(): which one filament would help this picture most? Try adding each
filament from the library and a catalogue of common ones, at every place in
the Stack, and rank them by how much the colour error drops.

suggest_set(): which 2, 3, 4 (or up to `most`) filaments should I buy and
load for this picture? More than 4 means Spool changes during the print. Builds a Stack from scratch: the best dark base + one more, then adds
the filament that helps most, then tries swapping each one out for a better
one. Owned filaments win ties, so it only asks you to buy what clearly helps."""
from itertools import combinations, permutations
from math import comb
import json
from pathlib import Path

import numpy as np

from .filaments import Filament, load_library
from .optics import srgb_to_lab
from .plan import _unique_lab, best_plan, layout_errors
from .spools import MAX_STACK

CATALOGUE = Path(__file__).with_name("catalogue.json")
BUY_COST = 0.5          # dE: a filament you own beats one you'd buy unless the new one is clearly better
WORTH_IT = 0.5          # dE: a bigger Stack must beat the smaller one by this much to be recommended


def candidates():
    """Library filaments first (you own them), then catalogue ones not already listed."""
    lib = load_library()
    out = {k: (f, True) for k, f in lib.items()}
    have = {f.hex.upper() for f in lib.values()}
    for k, v in json.loads(CATALOGUE.read_text()).items():
        if not k.startswith("_") and v["hex"].upper() not in have:
            v = {x: y for x, y in v.items() if x != "td_source"}
            out[k] = (Filament(key=k, slot=0, **v), False)
    return out


def stack_filaments(keys):
    """Filaments for a Stack given by key: your library first, then the catalogue,
    so a suggested set can be previewed before you own it. Catalogue filaments
    get the AMS slots the rest of the Stack leaves free."""
    lib, cands = load_library(), candidates()
    missing = [k for k in keys if k not in cands]
    if missing:
        raise ValueError(f"unknown filament(s) {missing}")
    used = {lib[k].slot for k in keys if k in lib}
    free = [s for s in (1, 2, 3, 4) if s not in used]
    out = []
    for k in keys:
        f = lib.get(k) or cands[k][0]
        if k not in lib:
            f = Filament(key=k, name=f.name, hex=f.hex, td=f.td, slot=free.pop(0) if free else 1)
        out.append(f)
    return out


def td_sources():
    """key -> 'maker' (the maker's own TD table), 'community' (one user's reading), 'guess', or 'yours' (your library)."""
    out = {k: v.get("td_source", "guess") for k, v in json.loads(CATALOGUE.read_text()).items() if not k.startswith("_")}
    out.update({k: "yours" for k in load_library()})
    return out


def suggest(rgb, stack, base_layers=5, max_layers=17, top=5, sample=None):
    """Returns (current error, [(error, filament, owned, position), ...] best first),
    only filaments that lower the error. position = index in the Stack (0 = bottom)."""
    sample = sample or 80
    if len(stack) >= MAX_STACK:
        raise ValueError(f"The Stack is full ({MAX_STACK} filaments); remove one to get a suggestion")
    _, now = best_plan(rgb, stack, base_layers, max_layers, sample=sample)
    score = _Scorer(rgb, base_layers, max_layers, sample=sample)
    keys = {f.key for f in stack}
    labs = [srgb_to_lab(np.array(f.rgb)) for f in stack]
    found = []
    for key, (f, owned) in candidates().items():
        # skip what is in the Stack already, or so close in colour it adds nothing new
        if key in keys or min(np.linalg.norm(srgb_to_lab(np.array(f.rgb)) - l) for l in labs) < 12:
            continue
        pos = min(range(len(stack) + 1), key=lambda p: score(stack[:p] + [f] + stack[p:]))
        found.append((score(stack[:pos] + [f] + stack[pos:]), f, owned, pos))
    # the quick score only ranks; give the best few their exact error
    found = [(best_plan(rgb, stack[:p] + [f] + stack[p:], base_layers, max_layers, sample=sample)[1], f, o, p)
             for _, f, o, p in sorted(found, key=lambda t: t[0])[:2 * top]]
    found = sorted((t for t in found if t[0] < now - 0.05), key=lambda t: t[0])
    return now, found[:top]


class _Scorer:
    """best_plan's error for many Stacks quickly: every swap layout of a Stack
    is scored at once, on a coarse set of the picture's colours. Only for
    ranking; the winner is checked with best_plan."""

    def __init__(self, rgb, base_layers, max_layers, sample=48, bits=4, first_layer=0.2, layer_h=0.08):
        h, w, _ = rgb.shape
        step = max(1, w // sample)
        self.lab, counts, _ = _unique_lab(rgb[::step, ::step], bits)
        self.w = counts / counts.sum()
        self.base, self.top = base_layers, max_layers
        self.t = np.full(max_layers, layer_h); self.t[0] = first_layer
        self.layouts = {}                                    # n filaments -> every swap layout
        self.memo = {}

    def __call__(self, fils):
        key = tuple(f.key for f in fils)
        if key not in self.memo:
            n = len(fils)
            if n not in self.layouts:
                self.layouts[n] = _layouts(self.base, self.top, n - 1)
            self.memo[key] = float(layout_errors(self.lab, self.w, fils, self.layouts[n], self.t, self.base).min())
        return self.memo[key]


def _layouts(lo, hi, n, most=1500):
    """Every swap layout, or for tall Stacks with many filaments the same fixed
    random `most` of them (enough to rank Stacks; best_plan places the swaps)."""
    if comb(hi - lo, n) <= most:
        return np.array(list(combinations(range(lo, hi), n))).reshape(-1, n)
    rng = np.random.default_rng(0)
    return np.unique(np.sort(np.stack([rng.choice(np.arange(lo, hi), n, replace=False) for _ in range(most)]), 1), axis=0)


def suggest_set(rgb, base_layers=5, max_layers=17, most=4, owned_only=False, pool=14):
    """The best Stack of 2..`most` (at most MAX_STACK) filaments for this picture, from your library
    plus the catalogue. Returns [(error, [Filament, ...] bottom to top, [owned, ...]), ...]
    one entry per Stack size, each checked with best_plan."""
    most = min(most, MAX_STACK)
    cands = [(f, o) for f, o in candidates().values() if o or not owned_only]
    labs = {f.key: srgb_to_lab(np.array(f.rgb)) for f, _ in cands}
    owned = {f.key for f, o in cands if o}
    def twin(f, g, de):            # same look: close colour, and similar TD or both near opaque (TD 1 or less)
        return (np.linalg.norm(labs[f.key] - labs[g.key]) < de
                and (max(f.td, g.td) <= 1 or max(f.td, g.td) < 1.5 * min(f.td, g.td)))
    keep = []                                                # owned ones come first and stay
    for f, o in cands:
        # don't suggest buying what you nearly have already
        if not any(twin(f, g, 10 if g.key in owned else 6) for g in keep):
            keep.append(f)
    score = _Scorer(rgb, base_layers, max_layers)
    cost = lambda fils: score(fils) + BUY_COST * sum(f.key not in owned for f in fils)

    # 2 filaments: a dark base (as HueForge prints usually start) and anything on top
    dark = []                      # dark bases mostly hide each other's TD, so one per colour is enough
    for f in keep:
        if labs[f.key][0] < 45 and all(np.linalg.norm(labs[f.key] - labs[g.key]) > 10 for g in dark):
            dark.append(f)
    stack = min(([b, t] for b in dark for t in keep if t is not b), key=cost)
    results = [stack]
    # rank every filament by how much it adds; the 4th filament is only looked for among the best few
    gain = {}
    while len(stack) < most:
        trials = []
        for f in (sorted(keep, key=lambda f: gain.get(f.key, np.inf))[:3 * pool] if gain else keep):
            if f in stack:
                continue
            best = min((stack[:p] + [f] + stack[p:] for p in range(1, len(stack) + 1)), key=cost)
            gain[f.key] = cost(best)
            trials.append(best)
        if not trials:
            break
        stack = min(trials, key=cost)
        # polish: swap each filament for one of the strongest others, then try every order above the base
        short = sorted((f for f in keep if f.key in gain), key=lambda f: gain[f.key])[:pool]
        better = True
        while better:
            better = False
            for i in range(len(stack)):
                for f in (short if i else dark):
                    if f in stack:
                        continue
                    trial = stack[:i] + [f] + stack[i + 1:]
                    if cost(trial) < cost(stack) - 1e-9:
                        stack, better = trial, True
            # every order above the base for small Stacks, else every swap of two filaments
            orders = (permutations(stack[1:]) if len(stack) <= 5 else
                      (stack[1:i] + [stack[j]] + stack[i + 1:j] + [stack[i]] + stack[j + 1:]
                       for i in range(1, len(stack)) for j in range(i + 1, len(stack))))
            for order in orders:
                trial = [stack[0], *order]
                if cost(trial) < cost(stack) - 1e-9:
                    stack, better = trial, True
        results.append(stack)
    out = []
    for fils in results:
        _, err = best_plan(rgb, fils, base_layers, max_layers, sample=80)
        out.append((float(err), fils, [f.key in owned for f in fils]))
    return out


def recommended(sets):
    """Index of the smallest Stack that the bigger ones don't clearly beat."""
    best = 0
    for i in range(1, len(sets)):
        if sets[i][0] < sets[best][0] - WORTH_IT:
            best = i
    return best


def describe_sets(sets):
    src = td_sources()
    pick = recommended(sets)
    out = []
    for i, (err, fils, owned) in enumerate(sets):
        out.append(f"{len(fils)} filaments: colour error {err:.1f}{'   <- recommended' if i == pick else ''}")
        for j, (f, o) in enumerate(zip(fils, owned)):
            how = {"maker": "from the maker", "community": "measured by one user"}.get(src.get(f.key), "a guess")
            note = "you have it" if o else f"buy; TD {f.td:g} {how}"
            out.append(f"  {'base' if j == 0 else f'then'} {f.name} ({f.hex}, {note})")
    return out
