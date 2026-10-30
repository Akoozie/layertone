"""Lit, slightly angled 'photo' of a printed Card: heightfield shading with cast
shadows, the surface texture (45-degree top lines, or the textured plate's grain for
a face-down card), the card edge and a soft drop shadow."""
import math
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageFilter


def _view(card):
    """What the renderer needs from a raised Card or a face-down InlayCard."""
    if hasattr(card, "plan"):
        plan = card.plan
        zs = np.cumsum(plan.thickness()) + plan.backing

        def edge(zmm):
            k = int(np.searchsorted(zs, zmm))
            return plan.filaments[sum(1 for s in plan.swaps if s <= k)].rgb
        return SimpleNamespace(z=card.z, colour=card.colour, px=card.px, corner=card.corner, edge=edge, texture="lines")
    body = card.filaments[0].rgb
    return SimpleNamespace(z=np.full(card.labels.shape, card.thickness), colour=card.front_colours()[card.labels],
                           px=card.px, corner=card.corner, edge=lambda zmm: body, texture="plate")


def shade(card, light=(-0.45, 0.55, 0.75)):
    z, px = card.z, card.px
    gy, gx = np.gradient(z, px)
    n = np.stack([-gx, gy, np.ones_like(z)], -1)          # image y is down; world y up
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    L = np.array(light, float); L /= np.linalg.norm(L)
    lam = np.clip(n @ L, 0, 1)
    # cast shadows: march toward the light in the image plane
    sx, sy = -L[0], L[1]                                   # pixel step direction toward light (x right, y down)
    k = np.hypot(sx, sy); sx, sy = sx / k, sy / k
    rise = L[2] / np.hypot(L[0], L[1]) * px                # mm the ray climbs per pixel step
    sh = np.zeros_like(z, bool)
    h, w = z.shape
    for d in range(1, 26):
        dx, dy = int(round(sx * d)), int(round(sy * d))
        zz = np.full_like(z, -1.0)
        ys, yd = slice(max(0, dy), h + min(0, dy)), slice(max(0, -dy), h - max(0, dy))
        xs, xd = slice(max(0, dx), w + min(0, dx)), slice(max(0, -dx), w - max(0, dx))
        zz[yd, xd] = z[ys, xs]
        sh |= zz > z + rise * d + 0.01
    sh = np.asarray(Image.fromarray(sh.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.6))) / 255.0
    H = (L + np.array([0, 0, 1.0])); H /= np.linalg.norm(H)
    spec = np.clip(n @ H, 0, 1) ** 40 * 0.10
    light_amt = 0.36 + 0.80 * lam * (1 - 0.40 * sh)
    rgb = card.colour * light_amt[..., None] + spec[..., None]
    if card.texture == "lines":   # top-surface lines, 0.42 mm apart at 45 degrees
        yy, xx = np.mgrid[:h, :w]
        rgb *= (1 + 0.018 * np.sin((xx + yy) * px / 0.42 * 2 * np.pi))[..., None]
    else:                          # textured PEI plate: a fine matte grain with a little sparkle
        g = np.random.default_rng(1).normal(0, 1, (h, w))
        g = np.asarray(Image.fromarray(((g * 40) + 128).clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7)),
                       dtype=float) / 128 - 1
        rgb = rgb * (1 + 0.05 * g)[..., None] + (np.clip(g - 0.35, 0, 1) * 0.12)[..., None]
    # slight vignette from the light side
    yy, xx = np.mgrid[:h, :w] / np.array([h, w])[:, None, None]
    rgb *= (1.04 - 0.08 * (xx * 0.6 + yy * 0.4))[..., None]
    return np.clip(rgb, 0, 1)


def photo(card, out_w=900, tilt=0.11, bg=("#d9d6d0", "#bfbab2")):
    card = _view(card)
    top = shade(card)
    h, w = top.shape[:2]
    from .card import outline
    alpha = outline((h, w), card.px, card.corner, True) if card.corner else np.ones((h, w))
    im = Image.fromarray((top * 255).astype(np.uint8)).convert("RGBA")
    im.putalpha(Image.fromarray((alpha * 255).astype(np.uint8)))
    pad = 260
    canvas_w, canvas_h = w + 2 * pad, h + 2 * pad
    big = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    big.paste(im, (pad, pad), im)
    # perspective: far (top) edge narrower, slight rotation feel
    t = tilt
    a = math.radians(-5)
    cx, cy = pad + w / 2, pad + h / 2
    base = [(-w / 2 * (1 - t), -h / 2 * (1 - t * 0.6)), (w / 2 * (1 - t), -h / 2 * (1 - t * 0.6)),
            (w / 2 * (1 + t * 0.25), h / 2), (-w / 2 * (1 + t * 0.25), h / 2)]
    quad_dst = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in base]
    src = [(pad, pad), (pad + w, pad), (pad + w, pad + h), (pad, pad + h)]
    coeffs = _coeffs(quad_dst, src)
    warped = big.transform(big.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    # card edge: the warped silhouette, shifted down by the card thickness
    thick = int(round(float(np.median(card.z)) / card.px * 0.6)) + 2
    sil = warped.split()[3]
    layers = Image.new("RGBA", big.size, (0, 0, 0, 0))
    face_z = float(np.median(card.z))
    for i in range(thick, 0, -1):
        rgb = card.edge(face_z * (thick - i) / thick)            # i = thick is the bottom of the card
        e = Image.new("RGBA", big.size, tuple(int(v * 255 * 0.72) for v in rgb) + (255,)); e.putalpha(sil)
        layers.alpha_composite(e, (0, i))
    # backdrop + soft shadow
    bgim = Image.new("RGB", big.size, bg[0])
    grad = Image.linear_gradient("L").resize(big.size)
    bgim = Image.composite(Image.new("RGB", big.size, bg[1]), bgim, grad)
    shadow = Image.new("RGBA", big.size, (30, 26, 22, 0))
    sa = sil.point(lambda v: v * 0.55)
    shadow.putalpha(sa)
    shadow = shadow.transform(big.size, Image.AFFINE, (1, 0, -28, 0, 1, -40)).filter(ImageFilter.GaussianBlur(26))
    out = bgim.convert("RGBA")
    out.alpha_composite(shadow)
    out.alpha_composite(layers)
    out.alpha_composite(warped)
    bbox = sil.getbbox()
    m = 70
    out = out.crop((bbox[0] - m, bbox[1] - m, bbox[2] + m, bbox[3] + m + thick))
    out = out.convert("RGB")
    return out.resize((out_w, round(out.height * out_w / out.width)), Image.LANCZOS)


def _coeffs(dst, src):
    """PIL PERSPECTIVE coefficients mapping output (dst) points back to input (src)."""
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        b += [u, v]
    return np.linalg.solve(np.array(A, float), np.array(b, float)).tolist()
