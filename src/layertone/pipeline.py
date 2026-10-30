"""Picture -> Swap plan -> Heights -> preview / mesh / 3MF. Shared by the CLI and the page."""
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .mesh import heightfield_mesh, mask_mesh
from .optics import srgb_to_lab, stack_colours
from .plan import Plan, best_plan, despeckle, dither, edge_mask, fractional_heights, heights
from .threemf import write_3mf, write_flat_3mf


def open_image(src):
    """Path or file object -> RGB PIL image, transparency flattened onto white."""
    img = ImageOps.exif_transpose(Image.open(src))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    return img.convert("RGB")


def tone(rgb, brightness=0.0, contrast=1.0):
    """brightness -1..1 lifts or darkens mid-tones (black and white stay put);
    contrast > 1 spreads tones away from mid grey, < 1 flattens them."""
    if brightness:
        rgb = rgb ** (2.0 ** -brightness)
    if contrast != 1.0:
        rgb = np.clip((rgb - 0.5) * contrast + 0.5, 0, 1)
    return rgb


def reduce_colours(rgb, k, iters=8):
    """k-means in Lab on the picture's distinct colours: every pixel becomes one
    of `k` colours. Flattens noise and film grain into clean areas."""
    from .plan import _unique_lab
    lab, counts, inverse = _unique_lab(rgb)
    w = counts.astype(float)
    # start from evenly spaced lightness quantiles, so dark and light both get centres
    order = np.argsort(lab[:, 0])
    cum = np.cumsum(w[order]) / w.sum()
    centres = lab[order[np.searchsorted(cum, (np.arange(k) + 0.5) / k)]]
    for _ in range(iters):
        lab_of = np.linalg.norm(lab[:, None] - centres, axis=-1).argmin(1)
        for c in range(k):
            m = lab_of == c
            if m.any():
                centres[c] = (lab[m] * w[m, None]).sum(0) / w[m].sum()
    lab_of = np.linalg.norm(lab[:, None] - centres, axis=-1).argmin(1)
    # each centre's colour = weighted mean sRGB of its members (no Lab->sRGB needed)
    flat = rgb.reshape(-1, 3)
    pix = lab_of[inverse.ravel()]
    out = np.zeros((k, 3))
    for c in range(k):
        m = pix == c
        if m.any():
            out[c] = flat[m].mean(0)
    return out[pix].reshape(rgb.shape)


def fit(img, width_mm, px, crop=None, detail=0.0, brightness=0.0, contrast=1.0, smooth=0.0, colours=0):
    """Crop, scale to one pixel per `px` mm and stretch contrast. Returns floats 0..1.

    detail 0..1 boosts local contrast (a wide unsharp mask, ~8 mm on the print)
    and then sharpens edges, done at print scale so it means the same at any size.
    smooth (mm) median-filters away grain and printed-photo dither dots first;
    colours > 0 reduces the picture to that many colours.
    """
    if crop:
        img = img.crop(tuple(crop))
    nx = max(2, int(round(width_mm / px)))
    ny = max(2, int(round(nx * img.height / img.width)))
    img = ImageOps.autocontrast(img.resize((nx, ny), Image.LANCZOS), cutoff=0.5)
    if smooth > 0:
        img = img.filter(ImageFilter.MedianFilter(2 * max(1, round(smooth / px / 2)) + 1))
    if detail > 0:
        img = img.filter(ImageFilter.UnsharpMask(radius=8 / px, percent=round(60 * detail), threshold=0))
        img = img.filter(ImageFilter.UnsharpMask(radius=0.4 / px, percent=round(120 * detail), threshold=2))
    rgb = tone(np.asarray(img, dtype=np.float64) / 255.0, brightness, contrast)
    return reduce_colours(rgb, colours) if colours else rgb


FRAME_STYLES = ("flat", "dark", "bevel", "cove", "steps", "mat", "double", "lip", "beads", "rounded")


def corner_mm(frame_px, style, px):
    return frame_px * px if style == "rounded" else 0.0


def _band_profile(f, thresholds, values):
    """1D integer profile of length f with each band at least 1 px wide (if f >= len(values))."""
    b = len(values)
    edges = [int(round(t * f)) for t in thresholds]
    widths = [edges[k + 1] - edges[k] for k in range(b)]
    if f >= b:
        while any(w == 0 for w in widths):
            zero_k = widths.index(0)
            widest_k = int(np.argmax(widths))
            widths[widest_k] -= 1
            widths[zero_k] += 1
    return np.repeat(values, widths)


def frame_heights(shape, f, style, lo, mid, hi):
    """Integer layer counts for a raised frame of width f around shape."""
    if style not in FRAME_STYLES:
        raise ValueError(f"Unknown frame style {style!r}: use one of {', '.join(FRAME_STYLES)}")
    f = int(f)
    if f <= 0:
        return np.zeros(shape, dtype=int)
    h_pad = shape[0] + 2 * f
    w_pad = shape[1] + 2 * f
    y_i = np.minimum(np.arange(h_pad), h_pad - 1 - np.arange(h_pad))
    x_i = np.minimum(np.arange(w_pad), w_pad - 1 - np.arange(w_pad))
    idx = np.clip(np.minimum(y_i[:, None], x_i[None, :]), 0, f - 1)

    if style == "flat":
        return np.full((h_pad, w_pad), hi, dtype=int)
    if style == "dark":
        return np.full((h_pad, w_pad), lo, dtype=int)
    if style == "bevel":
        d = np.arange(f) / (f - 1) if f > 1 else np.zeros(f)
        prof = np.clip(np.round(hi - (hi - lo) * d), lo, hi).astype(int)
        return prof[idx]
    if style == "cove":
        d = np.arange(f) / (f - 1) if f > 1 else np.zeros(f)
        prof = np.clip(np.round(lo + (hi - lo) * d ** 2), lo, hi).astype(int)
        return prof[idx]
    if style == "steps":
        prof = _band_profile(f, [0.0, 1 / 3, 2 / 3, 1.0], [hi, mid, lo])
        return prof[idx]
    if style == "mat":
        prof = _band_profile(f, [0.0, 0.85, 1.0], [hi, lo])
        return prof[idx]
    if style == "double":
        prof = _band_profile(f, [0.0, 0.5, 0.75, 0.875, 1.0], [hi, lo, hi, lo])
        return prof[idx]
    if style == "lip":
        prof = _band_profile(f, [0.0, 0.8, 1.0], [mid, hi])
        return prof[idx]
    if style == "beads":
        prof = _band_profile(f, [0.0, 0.15, 1.0], [hi, mid])
        out = prof[idx]
        r = 0.2 * f
        target_s = 2.75 * r
        lx = w_pad - 1.2 * f
        ly = h_pad - 1.2 * f
        nx = max(1, round(lx / target_s))
        ny = max(1, round(ly / target_s))
        xs = 0.6 * f + np.arange(nx + 1) * (lx / nx)
        ys = 0.6 * f + np.arange(ny + 1) * (ly / ny)
        centers = [(x, 0.6 * f) for x in xs] + [(x, h_pad - 0.6 * f) for x in xs]
        centers += [(0.6 * f, y) for y in ys[1:-1]] + [(w_pad - 0.6 * f, y) for y in ys[1:-1]]
        for cx, cy in centers:
            x0 = max(0, int(np.floor(cx - r)))
            x1 = min(w_pad, int(np.ceil(cx + r + 1)))
            y0 = max(0, int(np.floor(cy - r)))
            y1 = min(h_pad, int(np.ceil(cy + r + 1)))
            px_x = np.arange(x0, x1) + 0.5
            px_y = np.arange(y0, y1) + 0.5
            bead_mask = (px_x[None, :] - cx) ** 2 + (px_y[:, None] - cy) ** 2 <= r ** 2
            out[y0:y1, x0:x1][bead_mask] = hi
        return out
    if style == "rounded":
        return np.full((h_pad, w_pad), hi, dtype=int)


@dataclass
class Result:
    plan: Plan
    error: float           # mean colour error (CIE dE) on the planning thumbnail
    heights: np.ndarray    # layers per pixel
    corner: float = 0.0

    def preview(self):
        pal = (self.plan.palette() * 255).round().astype(np.uint8)
        return Image.fromarray(pal[self.heights - self.plan.base_layers])

    def z(self):
        return self.plan.z_top(self.heights)


def backing_mm(mm):
    """Backing is printed in 0.2 mm layers, so round it to a whole number of them."""
    return round(max(0.0, float(mm)) / 0.2) * 0.2


def render(rgb, filaments, base_layers=5, max_layers=17, clean=3, thin=0, dither_block=0, swaps=None,
           backing=0.0, frame=0, frame_style="flat", px=None):
    """clean: despeckle window in pixels (3 = drop lone pixels, 5 = blobs up to
    ~2x2; 0/1 = off). dither_block > 0: dither between layers in blocks of that many pixels
    (2 = 0.4 mm at 0.2 mm pixels, one nozzle line), keeping outlines sharp.
    backing: mm of solid first filament under the picture, so the panel isn't
    paper-thin; it sits under the opaque base, so the colours don't change.
    frame: a raised border this many pixels wide, as tall as the tallest point.
    frame_style: profile of the frame border (one of FRAME_STYLES)."""
    if swaps is not None and len(swaps) != len(filaments) - 1:
        swaps = None                                  # stack changed; plan again
    if swaps and not all(base_layers <= a < b for a, b in zip(swaps, list(swaps[1:]) + [max_layers])):
        raise ValueError("swap layers must rise, start at or above the base and stay under the top")
    plan, err = best_plan(rgb, filaments, base_layers, max_layers, thin=thin, swaps=swaps,
                          backing=backing_mm(backing))
    if dither_block:
        n = dither(fractional_heights(rgb, plan), dither_block, edge_mask(rgb))
        n = n.clip(plan.base_layers, plan.max_layers)
    else:
        n = heights(rgb, plan)
        if clean and clean > 1:
            n = despeckle(n, int(clean))
    if frame:
        f = int(frame)
        if f > 0:
            if frame_style not in FRAME_STYLES:
                raise ValueError(f"Unknown frame style {frame_style!r}: use one of {', '.join(FRAME_STYLES)}")
            lo = plan.base_layers
            hi = plan.max_layers
            if len(filaments) == 2:
                mid = (lo + hi) // 2
            else:
                k = len(filaments) // 2
                mid = plan.swaps[k] if k < len(plan.swaps) else hi
            ring = frame_heights(n.shape, f, frame_style, lo, mid, hi)
            ring[f:-f, f:-f] = n
            n = ring
    corner = corner_mm(int(frame), frame_style, px) if px is not None else 0.0
    return Result(plan, err, n, corner=corner)


def export_3mf(out, result, px, title, name, mask=None):
    """mask: optional bool outline to keep (e.g. card.outline for rounded corners)."""
    # stay under half the thinnest layer so every slice is unchanged
    verts, faces = heightfield_mesh(result.z(), px, max_error=0.4 * result.plan.thickness()[1:].min(), mask=mask)
    write_3mf(out, verts, faces, result.plan, result.preview(), title, name=name)
    return verts, faces


# ---- Flat Paint: flat pieces, one filament per colour (no layered blending) ----

def _box_sum(a, r):
    """Sum over a (2r+1) x (2r+1) window, edges padded by repeating."""
    p = np.pad(a, r + 1, mode="edge").cumsum(0).cumsum(1)
    n = 2 * r + 1
    h, w = a.shape
    return p[n:n + h, n:n + w] - p[:h, n:n + w] - p[n:n + h, :w] + p[:h, :w]


def mode_filter(labels, k, size=3):
    """Most common label in each size x size window: drops specks smaller than
    the window without blurring outlines like a mean would."""
    if size < 2:
        return labels
    votes = np.stack([_box_sum((labels == c).astype(np.int32), size // 2) for c in range(k)])
    return votes.argmax(0)


@dataclass
class FlatResult:
    filaments: list
    labels: np.ndarray       # filament index per pixel
    colours: np.ndarray      # (k, 3) sRGB each filament shows on top of the base
    base_z: float
    top_z: float

    def preview(self):
        return Image.fromarray((self.colours[self.labels] * 255).round().astype(np.uint8))

    def error(self, rgb):
        return float(np.linalg.norm(srgb_to_lab(rgb) - srgb_to_lab(self.colours[self.labels]), axis=-1).mean())


def flat_paint(rgb, filaments, base_layers=0, paint_layers=11, speck=3, first_layer=0.2, layer_h=0.08):
    """Each pixel takes the filament whose colour (as printed over the base in
    the first filament) is nearest. base_layers = 0 makes every colour full depth."""
    t = np.full(base_layers + paint_layers, layer_h); t[0] = first_layer
    cols = np.array([stack_colours([0] * base_layers + [k] * paint_layers, filaments, t)[-1]
                     for k in range(len(filaments))])
    lab = srgb_to_lab(rgb)
    labels = np.linalg.norm(lab[..., None, :] - srgb_to_lab(cols), axis=-1).argmin(-1)
    labels = mode_filter(labels, len(filaments), speck)
    z = np.cumsum(t)
    return FlatResult(filaments, labels, cols, float(z[base_layers - 1]) if base_layers else 0.0, float(z[-1]))


def export_flat_3mf(out, res, px, title, name):
    parts = []
    for k, f in enumerate(res.filaments):
        mask = res.labels == k
        pieces = []
        if k == 0 and res.base_z > 0:
            pieces.append(mask_mesh(np.ones_like(mask), px, 0.0, res.base_z))
        if mask.any():
            pieces.append(mask_mesh(mask, px, res.base_z, res.top_z))
        if not pieces:
            continue
        verts = np.concatenate([v for v, _ in pieces])
        offs = np.cumsum([0] + [len(v) for v, _ in pieces[:-1]])
        faces = np.concatenate([fc + o for (_, fc), o in zip(pieces, offs)])
        parts.append((verts, faces, f))
    write_flat_3mf(out, parts, res.preview(), title, name=name)
    return parts
