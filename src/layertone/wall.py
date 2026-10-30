"""Wall: one big picture printed as a grid of Tiles that fit the A1 bed.

The picture is planned and rendered once, then cut into tiles, so every tile
shares one Swap plan and the colours match across the seams. Neighbouring tiles
share their edge column of pixels, so the picture runs on without a gap.
Seams are plain vertical cuts (no Backing lip, no Frame); a Frame, if set,
only runs round the outside of the wall.

Joins go into the back (the face on the bed), never into the colour layers:
the Backing is made thick enough that every cut keeps COVER mm of it on top.

magnets  Ø5.4 bore, 4 crush ribs leaving 5.0 mm, 2.2 deep, 0.4 chamfer (a print-tested 5 x 2 mm
         magnet fit) on both sides of each seam, plus link plates holding the matching magnets
keys     butterfly (dovetail) recesses across each seam, plus keys that drop in
plates   peg holes on both sides of each seam, plus plates with two pegs that bridge it
none     flat back, for gluing onto a board or into a frame

Every tile has its label (A1 = top row, first column) engraved into the back,
mirrored so it reads from the back, with an arrow to the top.
"""
import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .mesh import heightfield_mesh
from .pipeline import Result

JOINS = ("magnets", "keys", "plates", "none")
MAX_TILE = 240.0           # mm; the A1 bed is 256, keep a margin for the skirt and wipe
COVER = 0.6                # mm of Backing left above any cut in the back
LABEL_DEPTH = 0.4          # first layer + one 0.2 mm Backing layer
DEPTH = {"magnets": 2.2, "keys": 1.6, "plates": 2.0, "none": 0.0}
INSET = {"magnets": 9.0, "keys": 0.0, "plates": 8.0, "none": 0.0}   # feature centre from the seam, mm
SPARES = 2                 # extra joining parts in the joins 3MF

# magnet pocket (memory: magnet-pockets, eSUN PLA+, 0.20 Standard, hole compensation 0)
BORE_R, RIB_R, RIB_GAP_R, CHAMFER = 2.7, 0.5, 2.5, 0.4
# butterfly key: half width at the seam and at the ends, length each side, clearance per side
KEY_NECK, KEY_END, KEY_HALF, KEY_GAP = 3.0, 6.0, 10.0, 0.15
PEG_HOLE_R, PEG_R = 2.2, 2.1


def _m():
    from .stand import _m
    return _m()


def wall_backing(backing, join):
    """Backing (mm, 0.2 mm steps) thick enough for the join's cuts and the label."""
    need = max(DEPTH[join], LABEL_DEPTH) + COVER
    return max(round(float(backing) / 0.2) * 0.2, math.ceil(need / 0.2 - 1e-9) * 0.2)


def grid(width_mm, height_mm, cols=0, rows=0, max_tile=MAX_TILE):
    """(cols, rows): the given ones, or the fewest that keep every tile under max_tile mm."""
    cols = int(cols) or max(1, math.ceil(width_mm / max_tile - 1e-9))
    rows = int(rows) or max(1, math.ceil(height_mm / max_tile - 1e-9))
    tw, th = width_mm / cols, height_mm / rows
    if max(tw, th) > max_tile + 1e-6:
        raise ValueError(f"Tiles would be {tw:.0f} x {th:.0f} mm; the A1 fits {max_tile:.0f} mm. "
                         f"Use more tiles or a smaller width.")
    return cols, rows


def label(r, c):
    return f"{chr(65 + r)}{c + 1}"


@dataclass
class Tile:
    row: int
    col: int
    heights: np.ndarray       # layers per pixel, edge columns shared with the neighbours
    x0: int                   # first pixel column / row in the whole wall
    y0: int

    @property
    def name(self):
        return label(self.row, self.col)

    def size_mm(self, px):
        h, w = self.heights.shape
        return (w - 1) * px, (h - 1) * px


def split(heights, cols, rows):
    """Cut a heights array into rows x cols tiles that share their edge pixels."""
    h, w = heights.shape
    xs = np.round(np.linspace(0, w - 1, cols + 1)).astype(int)
    ys = np.round(np.linspace(0, h - 1, rows + 1)).astype(int)
    return [Tile(r, c, heights[ys[r]:ys[r + 1] + 1, xs[c]:xs[c + 1] + 1], xs[c], ys[r])
            for r in range(rows) for c in range(cols)]


# ---- cutters for the back (z = 0 is the bed; cutters start below it) ----

def _poly(pts):
    """CrossSection of one polygon, wound counter-clockwise."""
    pts = [tuple(map(float, p)) for p in pts]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    return _m().CrossSection([pts if area > 0 else pts[::-1]])


def magnet_pocket(depth=DEPTH["magnets"]):
    """Ø5.4 bore with a 0.4 mm chamfer at the mouth (z = 0) and 4 round crush ribs at 45° leaving Ø5.0."""
    M = _m().Manifold
    bore = M.cylinder(depth + 0.5, BORE_R, BORE_R, 64).translate((0, 0, -0.5))
    cone = M.cylinder(CHAMFER + 0.5, BORE_R + CHAMFER + 0.5, BORE_R, 64).translate((0, 0, -0.5))
    rc = RIB_GAP_R + RIB_R
    ribs = [M.cylinder(depth + 1, RIB_R, RIB_R, 24).translate((rc * math.cos(a), rc * math.sin(a), CHAMFER))
            for a in np.radians([45, 135, 225, 315])]
    return (bore + cone) - M.batch_boolean(ribs, _m().OpType.Add)


def peg_hole(depth=DEPTH["plates"]):
    M = _m().Manifold
    return (M.cylinder(depth + 0.5, PEG_HOLE_R, PEG_HOLE_R, 48).translate((0, 0, -0.5))
            + M.cylinder(0.8, PEG_HOLE_R + 0.5, PEG_HOLE_R, 48).translate((0, 0, -0.5)))


def _bowtie_half(gap=0.0):
    """Half a butterfly in (u = distance in from the seam, v = along it), past the seam by 1 mm."""
    slope = (KEY_END - KEY_NECK) / KEY_HALF
    pts = [(-1, -(KEY_NECK - slope) - gap), (KEY_HALF + gap, -KEY_END - gap),
           (KEY_HALF + gap, KEY_END + gap), (-1, KEY_NECK - slope + gap)]
    return pts


def _to_xy(side, u, v, w, h):
    """Local (u in from the edge, v along it) -> tile (x, y). y = 0 is the bottom edge."""
    return {"left": (u, v), "right": (w - u, v), "bottom": (v, u), "top": (v, h - u)}[side]


def seam_spots(length):
    """Where the joins go along a seam `length` mm long: 2 or more, about 100 mm apart."""
    n = max(2, math.ceil(length / 100))
    return [(k + 0.5) * length / n for k in range(n)]


def tile_sides(t, cols, rows):
    """The tile's sides that meet another tile."""
    return [s for s, ok in (("left", t.col > 0), ("right", t.col < cols - 1),
                            ("top", t.row > 0), ("bottom", t.row < rows - 1)) if ok]


def join_cutters(join, sides, w, h):
    """The cuts for one tile's joins, in tile coordinates."""
    if join == "none":
        return []
    M = _m().Manifold
    out = []
    for side in sides:
        length = h if side in ("left", "right") else w
        for v in seam_spots(length):
            if join == "keys":
                pts = [_to_xy(side, uu, v + vv, w, h) for uu, vv in _bowtie_half()]
                out.append(M.extrude(_poly(pts), DEPTH[join] + 0.5).translate((0, 0, -0.5)))
            else:
                x, y = _to_xy(side, INSET[join], v, w, h)
                out.append((magnet_pocket() if join == "magnets" else peg_hole()).translate((x, y, 0)))
    return out


def _font(size_px):
    from .card import FONT
    return ImageFont.truetype(str(FONT), size_px)


def label_cutter(text, w, h, em=16.0, px=0.25, depth=LABEL_DEPTH):
    """The tile's label and an arrow to the top, mirrored so they read from the back, centred on the back."""
    m3 = _m()
    s = round(em / px)
    W, H = round(em * 3 / px), round(em * 2.2 / px)
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    d.text((W / 2, H * 0.98), text, font=_font(s), fill=255, anchor="md")
    a = round(em * 0.3 / px)                                         # arrow: triangle on a short stem
    d.polygon([(W / 2, 0), (W / 2 - 1.6 * a, 1.6 * a), (W / 2 + 1.6 * a, 1.6 * a)], fill=255)
    d.rectangle([W / 2 - a / 2, 1.6 * a, W / 2 + a / 2, 2.6 * a], fill=255)
    m = np.asarray(im)[:, ::-1] > 127                               # mirrored: it is read from the back
    rects = []
    for r, row in enumerate(m):
        dd = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        for a0, a1 in zip(np.flatnonzero(dd == 1), np.flatnonzero(dd == -1)):
            # +0.02 mm overlap so neighbouring rows union into one shape
            rects.append(m3.CrossSection.square((float(a1 - a0) * px, px + 0.02))
                         .translate((float(a0) * px, float(H - 1 - r) * px - 0.01)))
    cs = m3.CrossSection.batch_boolean(rects, m3.OpType.Add)
    return (m3.Manifold.extrude(cs, depth + 0.5)
            .translate((w / 2 - W * px / 2, h / 2 - H * px / 2, -0.5)))


def tile_mesh(t, plan, px, join, cols, rows, max_error, mask=None):
    """(verts, faces) of one tile with its joins and label cut into the back."""
    m3 = _m()
    verts, faces = heightfield_mesh(plan.z_top(t.heights), px, max_error=max_error, mask=mask)
    body = m3.Manifold(m3.Mesh(vert_properties=verts.astype(np.float32), tri_verts=faces.astype(np.uint32)))
    if body.status() != m3.Error.NoError:
        raise ValueError(f"tile {t.name}: mesh is not closed ({body.status()})")
    w, h = t.size_mm(px)
    cuts = join_cutters(join, tile_sides(t, cols, rows), w, h) + [label_cutter(t.name, w, h)]
    body = body - m3.Manifold.batch_boolean(cuts, m3.OpType.Add)
    mesh = body.to_mesh()
    return np.asarray(mesh.vert_properties[:, :3], float), np.asarray(mesh.tri_verts, np.int64)


# ---- the separate joining parts ----

def _rounded(lx, ly, r):
    return _m().CrossSection.square((lx - 2 * r, ly - 2 * r), center=True).offset(r, circular_segments=32)


def join_part(join):
    """One joining part, flat on the bed, or None. Magnet links: pockets open at the top, 18 mm apart."""
    M = _m().Manifold
    if join == "magnets":
        t = DEPTH["magnets"] + 0.8
        plate = M.extrude(_rounded(2 * INSET["magnets"] + 12, 12, 3), t)
        pocket = magnet_pocket().mirror((0, 0, 1)).translate((0, 0, t))
        return plate - pocket.translate((-INSET["magnets"], 0, 0)) - pocket.translate((INSET["magnets"], 0, 0))
    if join == "keys":
        pts = [(-KEY_HALF + KEY_GAP, -KEY_END + KEY_GAP), (0, -KEY_NECK + KEY_GAP), (KEY_HALF - KEY_GAP, -KEY_END + KEY_GAP),
               (KEY_HALF - KEY_GAP, KEY_END - KEY_GAP), (0, KEY_NECK - KEY_GAP), (-KEY_HALF + KEY_GAP, KEY_END - KEY_GAP)]
        return M.extrude(_poly(pts), DEPTH["keys"] - 0.1)
    if join == "plates":
        plate = M.extrude(_rounded(2 * INSET["plates"] + 10, 10, 2.5), 2.0)
        peg = M.cylinder(DEPTH["plates"] - 0.2, PEG_R, PEG_R * 0.9, 48).translate((0, 0, 2.0))
        return plate + peg.translate((-INSET["plates"], 0, 0)) + peg.translate((INSET["plates"], 0, 0))
    return None


def joins_plate(join, n):
    """n joining parts in rows on the bed, as one (verts, faces) or None."""
    part = join_part(join)
    if part is None or n == 0:
        return None
    lo, hi = np.array(part.bounding_box()[:3]), np.array(part.bounding_box()[3:])
    dx, dy = hi[0] - lo[0] + 4, hi[1] - lo[1] + 4
    per_row = max(1, int(200 // dx))
    parts = [part.translate((float((k % per_row) * dx), float((k // per_row) * dy), 0)) for k in range(n)]
    mesh = _m().Manifold.batch_boolean(parts, _m().OpType.Add).to_mesh()
    return np.asarray(mesh.vert_properties[:, :3], float), np.asarray(mesh.tri_verts, np.int64)


# ---- the layout sheet and the whole export ----

HOW = {
    "magnets": ["Press a 5 x 2 mm magnet into every pocket on the backs, all the same pole out (mark it).",
                "Press magnets into the links with the other pole up, so they pull onto the tiles.",
                "Lay the tiles face down in the layout above and drop a link across each seam."],
    "keys": ["Lay the tiles face down in the layout above, edges touching.",
             "Tap a butterfly key into each recess across a seam; a drop of glue makes it permanent."],
    "plates": ["Lay the tiles face down in the layout above, edges touching.",
               "Push a peg plate into each pair of holes across a seam; add glue for a permanent wall."],
    "none": ["The backs are flat: glue the tiles onto a board or into a frame, edges touching."],
}


def _wrap(d, text, font, width):
    """Split text into lines no wider than `width` px."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and d.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur]


def layout_sheet(result, tiles, cols, rows, px, join, n_joins, title):
    """PNG of the wall from the front with the tile labels, sizes and how to put it together."""
    prev = result.preview()
    W, pad, top = 1400, 40, 80
    scale = W / prev.width
    pic = prev.resize((W, round(prev.height * scale)), Image.LANCZOS)
    f, f_big = _font(24), _font(max(28, round(min(pic.width / cols, pic.height / rows) / 4)))
    plan = result.plan
    sw = ", ".join(f"{fl.name} at {z:.2f} mm" for z, fl in zip(plan.swap_z(), plan.filaments[1:]))
    w_mm, h_mm = (result.heights.shape[1] - 1) * px, (result.heights.shape[0] - 1) * px
    lines = [f"Wall {w_mm:.0f} x {h_mm:.0f} mm, {len(tiles)} tiles of about {tiles[0].size_mm(px)[0]:.0f} x "
             f"{tiles[0].size_mm(px)[1]:.0f} mm, {float(result.z().max()):.2f} mm thick.",
             f"Every tile uses the same swaps: start in {plan.filaments[0].name}" + (f", then {sw}." if sw else "."),
             "Each tile's label is engraved on its back with an arrow to the top.",
             f"Joins: {join}" + (f", {n_joins} needed (+{SPARES} spares in the joins 3MF)." if join != "none" else ".")] + HOW[join]
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wrapped = [w for line in lines for w in _wrap(probe, line, f, W)]
    sheet = Image.new("RGB", (W + 2 * pad, top + pic.height + 24 + 34 * len(wrapped) + pad), "white")
    d = ImageDraw.Draw(sheet)
    d.text((pad, 20), f"{title}: {cols} x {rows} wall, seen from the front", font=_font(34), fill="black")
    sheet.paste(pic, (pad, top))
    for t in tiles:
        x0, y0 = pad + t.x0 * scale, top + t.y0 * scale
        tw, th = (t.heights.shape[1] - 1) * scale, (t.heights.shape[0] - 1) * scale
        d.rectangle([x0, y0, x0 + tw, y0 + th], outline=(255, 60, 60), width=3)
        d.text((x0 + tw / 2, y0 + th / 2), t.name, font=f_big, fill="white", anchor="mm",
               stroke_width=4, stroke_fill="black")
    y = top + pic.height + 24
    for line in wrapped:
        d.text((pad, y), line, font=f, fill="black")
        y += 34
    return sheet


def join_count(cols, rows, tile_w, tile_h):
    """Joining parts needed: one per spot along every seam."""
    return (cols - 1) * rows * len(seam_spots(tile_h)) + (rows - 1) * cols * len(seam_spots(tile_w))


def summary(width_mm, height_mm, cols, rows, join):
    """What the page shows for a wall: grid, tile size, joins needed, and a warning if a tile is too big."""
    tw, th = width_mm / cols, height_mm / rows
    warn = None
    if max(tw, th) > MAX_TILE + 1e-6:
        warn = f"Tiles would be {tw:.0f} x {th:.0f} mm; the A1 fits {MAX_TILE:.0f} mm. Use more tiles or a smaller width."
    return {"cols": cols, "rows": rows, "tile_mm": [round(tw, 1), round(th, 1)], "warning": warn,
            "joins": 0 if join == "none" else join_count(cols, rows, tw, th)}


def parse(wall):
    """'auto', '2x2' ... -> (cols, rows) with 0 meaning 'as many as needed'."""
    if not wall or str(wall).lower() == "auto":
        return 0, 0
    c, r = str(wall).lower().split("x")
    return int(c), int(r)


def overlay(img, cols, rows):
    """Red grid lines and tile labels drawn over a preview picture (a copy)."""
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    W, H = img.size
    for c in range(1, cols):
        d.line([(round(W * c / cols), 0), (round(W * c / cols), H)], fill=(255, 60, 60), width=2)
    for r in range(1, rows):
        d.line([(0, round(H * r / rows)), (W, round(H * r / rows))], fill=(255, 60, 60), width=2)
    f = _font(max(10, min(W // cols, H // rows) // 5))
    for r in range(rows):
        for c in range(cols):
            d.text((W * (c + 0.5) / cols, H * (r + 0.5) / rows), label(r, c), font=f, fill="white",
                   anchor="mm", stroke_width=2, stroke_fill="black")
    return img


def export_wall(out_dir, result, px, cols, rows, join="magnets", title="layertone", max_error=None, mask=None):
    """Write <title>_<A1..>.3mf, <title>_joins.3mf, <title>_layout.png and <title>_wall.zip
    holding them all into out_dir. Returns a list of (file name, note)."""
    if join not in JOINS:
        raise ValueError(f"Unknown join {join!r}: use one of {', '.join(JOINS)}")
    from .stand import write_stand_3mf
    from .threemf import write_3mf
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = result.plan
    if max_error is None:
        max_error = 0.4 * plan.thickness()[1:].min()
    tiles = split(result.heights, cols, rows)
    tile_masks = None
    if mask is not None:
        h, w = result.heights.shape
        xs = np.round(np.linspace(0, w - 1, cols + 1)).astype(int)
        ys = np.round(np.linspace(0, h - 1, rows + 1)).astype(int)
        tile_masks = [mask[ys[r]:ys[r + 1] + 1, xs[c]:xs[c + 1] + 1]
                      for r in range(rows) for c in range(cols)]
    files = []
    for idx, t in enumerate(tiles):
        tw, th = t.size_mm(px)
        if max(tw, th) > MAX_TILE + 1e-6:
            raise ValueError(f"Tile {t.name} is {tw:.0f} x {th:.0f} mm; the A1 fits {MAX_TILE:.0f} mm")
        t_mask = tile_masks[idx] if tile_masks is not None else None
        verts, faces = tile_mesh(t, plan, px, join, cols, rows, max_error, mask=t_mask)
        name = f"{title}_{t.name}.3mf"
        tile_res = Result(plan, result.error, t.heights)
        write_3mf(out_dir / name, verts, faces, plan, tile_res.preview(), f"{title} {t.name}", name=f"{title}_{t.name}.stl")
        files.append((name, f"{tw:.0f} x {th:.0f} mm, {len(faces)} triangles"))
    n = sum((len(seam_spots(t.size_mm(px)[1])) if t.col < cols - 1 else 0)
            + (len(seam_spots(t.size_mm(px)[0])) if t.row < rows - 1 else 0) for t in tiles)
    jp = joins_plate(join, n + SPARES) if n else None
    if jp:
        name = f"{title}_joins.3mf"
        write_stand_3mf(out_dir / name, *jp, filament=plan.filaments[0].key, title=f"{title} joins ({join})")
        files.append((name, f"{n + SPARES} {join} parts, one colour, 0.20 mm layers"))
    sheet = layout_sheet(result, tiles, cols, rows, px, join, n, title)
    sheet.save(out_dir / f"{title}_layout.png")
    files.append((f"{title}_layout.png", "where each tile goes"))
    zname = f"{title}_wall.zip"
    with zipfile.ZipFile(out_dir / zname, "w", zipfile.ZIP_STORED) as z:     # 3MFs are already compressed
        for name, _ in files:
            z.write(out_dir / name, name)
    files.append((zname, "all of the above"))
    return files, tiles


def wall_zip(result, px, cols, rows, join, title, mask=None):
    """The whole wall as zip bytes, for the page."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        export_wall(d, result, px, cols, rows, join, title, mask=mask)
        return (Path(d) / f"{title}_wall.zip").read_bytes()
