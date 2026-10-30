"""Swap planning: choose at which layers each filament starts, and how tall
each pixel is, so the print's colours come closest to the image."""
from dataclasses import dataclass
from itertools import combinations
from math import comb
import numpy as np

from .optics import TD_SCALE, stack_colours, srgb_to_lab


@dataclass
class Plan:
    filaments: list          # bottom to top
    swaps: list              # layer index (0 = first layer) where filament j+1 starts
    base_layers: int         # every pixel is at least this many layers tall
    max_layers: int
    first_layer: float
    layer_h: float
    thin: int = 0            # thin layers right after the first swap (see thickness)
    thin_h: float = 0.04
    backing: float = 0.0     # mm of solid first filament under everything, printed in 0.2 mm layers

    def thickness(self):
        """mm per layer. One light layer over a dark one changes brightness the
        most, so the first `thin` layers after the first swap can be thinner
        to fill the big gap between the darkest tones."""
        t = np.full(self.max_layers, self.layer_h)
        t[0] = self.first_layer
        if self.thin and self.swaps:
            t[self.swaps[0]:self.swaps[0] + self.thin] = self.thin_h
        return t

    def layers(self):
        """Filament index for every layer up to max_layers."""
        idx = np.zeros(self.max_layers, dtype=int)
        for j, s in enumerate(self.swaps):
            idx[s:] = j + 1
        return idx

    def palette(self):
        """sRGB of each allowed height, base_layers..max_layers."""
        cols = stack_colours(self.layers(), self.filaments, self.thickness())
        return cols[self.base_layers - 1:]

    def z_top(self, n_layers):
        return np.cumsum(self.thickness())[np.asarray(n_layers) - 1] + self.backing

    def backing_range(self):
        """(bottom, top) Z of the backing's 0.2 mm layers above the first layer, or None."""
        return (self.first_layer, round(self.first_layer + self.backing, 2)) if self.backing else None

    def thin_range(self):
        """(bottom, top) Z of the thin layers, or None."""
        if not (self.thin and self.swaps):
            return None
        s = self.swaps[0]
        return round(float(self.z_top(s)), 2), round(float(self.z_top(s + self.thin)), 2)

    def swap_z(self):
        """top_z of the first layer of each new filament (what Bambu Studio shows)."""
        return [round(float(self.z_top(s + 1)), 2) for s in self.swaps]


def _unique_lab(rgb, bits=6):
    """Distinct colours of the picture (rounded to `bits` per channel) in Lab,
    with how often each occurs and the index map back to the pixels.
    Pictures have far fewer distinct colours than pixels, so this is much faster."""
    q = np.round(rgb.reshape(-1, 3) * (2 ** bits - 1)).astype(np.int32)
    keys = (q[:, 0] << (2 * bits)) | (q[:, 1] << bits) | q[:, 2]
    uniq, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    m = 2 ** bits - 1
    cols = np.stack([uniq >> (2 * bits), (uniq >> bits) & m, uniq & m], -1) / m
    return srgb_to_lab(cols), counts, inverse.reshape(rgb.shape[:2])


def nearest(lab_pixels, palette_rgb):
    pal = srgb_to_lab(palette_rgb)
    d = np.linalg.norm(lab_pixels[..., None, :] - pal, axis=-1)
    return d.argmin(-1), d.min(-1)


SEARCH_ALL = 5000       # swap layouts all ranked at once; more than this and best_plan searches instead
SHORTLIST = 8           # layouts from the quick ranking that get the exact score


def layout_errors(lab, weights, filaments, layouts, thickness, base_layers):
    """Mean colour error of many swap layouts at once (no thin layers): for
    ranking only. lab, weights: the picture's colours; layouts: (K, swaps) array."""
    layouts = np.asarray(layouts).reshape(len(layouts), -1)
    n_layers = len(thickness)
    rgb = np.array([f.rgb for f in filaments])
    alpha = 1 - np.exp(-np.asarray(thickness)[None, :] / (np.array([f.td for f in filaments])[:, None] * TD_SCALE))
    lab2 = (lab ** 2).sum(1)[:, None]
    out = []
    for k in range(0, len(layouts), 256):
        idx = (np.arange(n_layers)[None, :, None] >= layouts[k:k + 256, None, :]).sum(-1)     # (K, layers)
        c = rgb[idx[:, 0]]
        pal = np.zeros(idx.shape + (3,))
        for i in range(n_layers):
            a = alpha[idx[:, i], i][:, None]
            c = c * (1 - a) + rgb[idx[:, i]] * a
            pal[:, i] = c
        pal = srgb_to_lab(pal[:, base_layers - 1:]).reshape(-1, 3)
        d2 = lab2 + (pal ** 2).sum(1)[None] - 2 * lab @ pal.T
        d = np.sqrt(d2.reshape(len(lab), len(idx), -1).min(-1).clip(0))
        out.append(weights @ d)
    return np.concatenate(out) if out else np.zeros(0)


def best_plan(rgb, filaments, base_layers=5, max_layers=17,
              first_layer=0.2, layer_h=0.08, sample=160, thin=0, swaps=None, backing=0.0):
    """Rank every swap layout quickly (or, for very many, search from spread-out
    ones), give the best few the exact score and keep the lowest mean colour error.
    `swaps` fixes the layout by hand (layer index where each filament starts).
    Stacks with more filaments than AMS slots only get layouts that leave a
    layer free to pause on for every Spool change (spools.py).

    rgb: (h, w, 3) floats 0..1. Only a `sample`-wide thumbnail is scored.
    """
    from .spools import SLOTS, feasible
    h, w, _ = rgb.shape
    step = max(1, w // sample)
    lab, counts, _ = _unique_lab(rgb[::step, ::step])
    weights = counts / counts.sum()
    n_swaps = len(filaments) - 1
    if n_swaps == 0:
        thin = 0
    if n_swaps > max_layers - base_layers:
        raise ValueError(f"{len(filaments)} filaments need at least {n_swaps} layers between the base and the top")

    def exact(layout):
        plan = Plan(filaments, list(layout), base_layers, max_layers, first_layer, layer_h, thin, backing=backing)
        return nearest(lab, plan.palette())[1] @ weights, plan

    if swaps:
        return exact(tuple(swaps))[::-1]
    if n_swaps == 0:
        return exact(())[::-1]
    changes = len({f.key for f in filaments}) > SLOTS
    ok = (lambda l: feasible(filaments, list(l))) if changes else (lambda l: True)
    ql, qc, _ = _unique_lab(rgb[::step * 2, ::step * 2], bits=4)
    qw = qc / qc.sum()
    t = np.full(max_layers, layer_h); t[0] = first_layer
    if comb(max_layers - base_layers, n_swaps) <= SEARCH_ALL:
        layouts = [l for l in combinations(range(base_layers, max_layers), n_swaps) if ok(l)]
        if not layouts:
            raise ValueError("no swap layout leaves a free layer for every spool change; raise the top layer")
        quick = layout_errors(ql, qw, filaments, layouts, t, base_layers)
        short = [layouts[i] for i in np.argsort(quick)[:SHORTLIST]]
    else:
        memo = {}
        def quick(l):
            if l not in memo:
                memo[l] = layout_errors(ql, qw, filaments, [l], t, base_layers)[0] if ok(l) else np.inf
            return memo[l]
        short = [_search(quick, n_swaps, base_layers, max_layers)]
        if quick(short[0]) == np.inf:
            raise ValueError("no swap layout leaves a free layer for every spool change; raise the top layer")
    err, plan = min((exact(l) for l in short), key=lambda e: e[0])
    return plan, err


def _search(score, n, lo, hi):
    """Move one swap at a time while it helps, from a few spread-out starts."""
    best = None
    span = hi - lo
    for shift in (0.0, 0.25, 0.5):
        cur = tuple(sorted(set(min(hi - 1, lo + int((i + shift) * span / n)) for i in range(n))))
        if len(cur) < n:
            cur = tuple(range(lo, lo + n))
        better = True
        while better:
            better = False
            for i in range(n):
                for d in (-2, -1, 1, 2):
                    t = list(cur); t[i] += d
                    if not all(lo <= a < b for a, b in zip(t, t[1:] + [hi])):
                        continue
                    if score(tuple(t)) < score(cur) - 1e-9:
                        cur, better = tuple(t), True
        if best is None or score(cur) < score(best):
            best = cur
    return best


def heights(rgb, plan):
    """Layer count per pixel, chosen as the nearest printable colour."""
    lab, _, inverse = _unique_lab(rgb)
    idx, _ = nearest(lab, plan.palette())
    return plan.base_layers + idx[inverse]


def despeckle(n, size=3):
    """Drop specks without eating line art. At every layer, islands (and holes)
    of at most size*size // 2 pixels (4 for size 3 = 0.16 mm2 at 0.2 mm pixels)
    are flattened into what surrounds them; a nozzle can't print them anyway
    and they give the slicer thousands of tiny islands. A letter stroke is a
    long connected run, so it stays however thin. (A plain size x size median
    erased 0.2 mm strokes: a trading-card test's small print came out as mush.)"""
    from scipy.ndimage import label
    amax = size * size // 2
    if amax < 1:
        return n
    h = n.copy()
    for _ in range(2):                     # a second pass catches specks the first one uncovered
        for k in range(int(h.max()), int(h.min()), -1):
            for up in (True, False):
                lab, count = label(h >= k if up else h < k)
                if not count:
                    continue
                small = np.bincount(lab.ravel()) <= amax
                small[0] = False
                h[small[lab]] = k - 1 if up else k
    return h


def fractional_heights(rgb, plan):
    """Like heights(), but between layers: each pixel is placed on the line
    between its nearest printable colour and the better of that colour's two
    neighbours, so 6.4 means "40 % of the way from layer 6 to layer 7"."""
    lab, _, inverse = _unique_lab(rgb)
    pal = srgb_to_lab(plan.palette())
    i = np.linalg.norm(lab[:, None] - pal, axis=-1).argmin(1)
    best_f = i.astype(float)
    best_d = np.full(len(lab), np.inf)
    for step in (-1, 1):
        j = np.clip(i + step, 0, len(pal) - 1)
        seg = pal[j] - pal[i]
        L2 = (seg ** 2).sum(1)
        t = np.where(L2 > 0, ((lab - pal[i]) * seg).sum(1) / np.where(L2 > 0, L2, 1), 0).clip(0, 1)
        d = np.linalg.norm(lab - (pal[i] + t[:, None] * seg), axis=1)
        better = d < best_d
        best_f = np.where(better, i + t * (j - i), best_f)
        best_d = np.where(better, d, best_d)
    return plan.base_layers + best_f[inverse]


def dither(f, block=2, edges=None):
    """Error-diffuse fractional Heights on blocks of `block` x `block` pixels,
    so every dot is at least one nozzle line wide. Pixels flagged in `edges`
    keep plain rounding, so outlines stay sharp. Returns integer Heights."""
    h, w = f.shape
    H, W = -(-h // block), -(-w // block)
    pad = np.pad(f, ((0, H * block - h), (0, W * block - w)), mode="edge")
    g = pad.reshape(H, block, W, block).mean((1, 3))
    out = np.zeros((H, W), dtype=int)
    for y in range(H):
        row, nxt = g[y], g[y + 1] if y + 1 < H else None
        for x in range(W):
            q = int(round(row[x]))
            out[y, x] = q
            e = row[x] - q
            if x + 1 < W:
                row[x + 1] += e * 7 / 16
            if nxt is not None:
                if x:
                    nxt[x - 1] += e * 3 / 16
                nxt[x] += e * 5 / 16
                if x + 1 < W:
                    nxt[x + 1] += e / 16
    n = np.repeat(np.repeat(out, block, 0), block, 1)[:h, :w]
    if edges is not None:
        n = np.where(edges, np.round(f).astype(int), n)
    return n


def edge_mask(rgb, strength=0.12):
    """Pixels on a strong outline (a big brightness step to a neighbour)."""
    from .optics import srgb_to_lab as lab
    L = lab(rgb)[..., 0] / 100
    gx = np.abs(np.diff(L, axis=1, append=L[:, -1:]))
    gy = np.abs(np.diff(L, axis=0, append=L[-1:, :]))
    return np.maximum(gx, gy) > strength
