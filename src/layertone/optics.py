"""How a stack of thin filament layers looks from above.

Each printed layer lets some of the colour below it through. A layer of
thickness t of a filament with transmission distance TD covers what is below
by alpha = 1 - exp(-t / (TD * TD_SCALE)).

Colours are mixed in sRGB, not linear light. Linear light is physically
truer but crushed the shadows in testing: one white layer jumped straight to
mid grey. sRGB mixing matches a black-and-white portrait test print, which looked right.

TD_SCALE = 0.12 makes Jade White (TD 3) hide ~63% of black at 0.36 mm, the
value that print was tuned with. Both are guesses until a calibration print
says otherwise.
"""
import numpy as np

TD_SCALE = 0.12


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_to_lab(rgb):
    lin = srgb_to_linear(rgb)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def layer_alpha(thickness, td):
    return 1.0 - np.exp(-thickness / (td * TD_SCALE))


def stack_colours(layers, filaments, thickness):
    """Colour seen from above for every stack height 1..len(layers).

    layers: filament index per printed layer, bottom first; thickness: mm per layer.
    Returns (n, 3) sRGB, row k = what a pixel k+1 layers tall looks like.
    """
    out = np.zeros((len(layers), 3))
    c = np.array(filaments[layers[0]].rgb)        # the plate side is lit from above only
    for i, (f_idx, t) in enumerate(zip(layers, thickness)):
        f = filaments[f_idx]
        a = layer_alpha(t, f.td)
        c = c * (1 - a) + np.array(f.rgb) * a
        out[i] = c
    return out
