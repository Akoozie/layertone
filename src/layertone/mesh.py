"""Heightfield to a closed, indexed triangle mesh (and binary STL)."""
import struct
import numpy as np
from pydelatin import Delatin


def heightfield_mesh(z, px, max_error=0.03, mask=None):
    """z: (ny, nx) top heights in mm, row 0 = image top. Flat bottom at 0.
    mask: optional (ny, nx) bool, the pixels to keep (a convex outline, such as a
    card with rounded corners); the rest is cut away at pixel resolution.

    The top is an error-bounded triangulation (Delatin): flat areas become a
    few big triangles instead of two per pixel. max_error stays under half a
    0.08 mm layer, so every slice the printer makes is unchanged.
    Returns (vertices (n,3) float, faces (m,3) int), outward normals.
    """
    z = np.ascontiguousarray(z, dtype=np.float64)          # Delatin puts row 0 at the top (+Y) itself
    ny, nx = z.shape
    if mask is not None:
        z = np.where(mask, z, 0.0)                         # a cliff, so Delatin puts vertices along the outline
    d = Delatin(z, max_error=max_error)
    top = d.vertices.astype(np.float64)
    tri = d.triangles.astype(np.int64)
    if mask is not None:
        inside = mask[ny - 1 - top[:, 1].astype(int), top[:, 0].astype(int)]
        tri = tri[inside[tri].all(1)]
        used = np.unique(tri)
        remap = np.full(len(top), -1); remap[used] = np.arange(len(used))
        top, tri = top[used], remap[tri]
    top[:, :2] *= px
    t = top[tri]
    up = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])[:, 2] > 0
    tri[~up] = tri[~up][:, ::-1]                            # counter-clockwise from above

    # outline = top edges used by one triangle, already running counter-clockwise
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    key = np.sort(e, 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    edge = e[cnt[inv.ravel()] == 1]
    rim = np.unique(edge)
    lo_of = np.full(len(top), -1); lo_of[rim] = len(top) + np.arange(len(rim))
    lo = top[rim].copy(); lo[:, 2] = 0
    centre_id = len(top) + len(rim)
    verts = np.concatenate([top, lo, [[(nx - 1) * px / 2, (ny - 1) * px / 2, 0.0]]])

    a, b = edge[:, 0], edge[:, 1]
    faces = [tri,
             np.stack([a, lo_of[a], lo_of[b]], -1),                      # walls
             np.stack([a, lo_of[b], b], -1),
             np.stack([np.full(len(a), centre_id), lo_of[b], lo_of[a]], -1)]  # bottom
    return verts, np.concatenate(faces)


def _runs(row):
    """[start, end) of each True run in a boolean row."""
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def mask_mesh(mask, px, z0, z1):
    """Closed mesh of the pixels in `mask` (row 0 = image top) as a slab from
    z0 to z1 mm, for Flat Paint parts.

    Top and bottom are one strip per run of pixels in a row. Each strip edge
    gets a vertex wherever a run starts or ends in the neighbouring row, so
    strips and walls share every vertex and the mesh is watertight without
    two triangles per pixel."""
    h, w = mask.shape
    runs = [_runs(r) for r in mask] + [[]]
    ends = [sorted({x for r in rr for x in r}) for rr in runs]     # run ends per row
    vid, verts, faces = {}, [], []

    def v(x, line, top):
        k = (x, line, top)
        if k not in vid:
            vid[k] = len(verts)
            verts.append((x * px, (h - line) * px, z1 if top else z0))
        return vid[k]

    def tri(a, b, c, up):
        faces.append((a, b, c) if up else (a, c, b))

    for y in range(h):
        for a, b in runs[y]:
            inner = lambda e: [x for x in e if a < x < b]
            top_line = [a] + inner(ends[y - 1] if y else []) + [b]       # on grid line y
            bot_line = [a] + inner(ends[y + 1]) + [b]                    # on grid line y + 1
            for top in (True, False):
                i = j = 0
                while i < len(top_line) - 1 or j < len(bot_line) - 1:
                    if j == len(bot_line) - 1 or (i < len(top_line) - 1 and top_line[i + 1] <= bot_line[j + 1]):
                        # +Y is up the image, so (x, line y) -> (x+, line y) -> (x, line y+1) is clockwise from above
                        tri(v(top_line[i], y, top), v(bot_line[j], y + 1, top), v(top_line[i + 1], y, top), top)
                        i += 1
                    else:
                        tri(v(top_line[i], y, top), v(bot_line[j], y + 1, top), v(bot_line[j + 1], y + 1, top), top)
                        j += 1
            # side walls at the run ends: outward is -X at a, +X at b
            for x, out in ((a, -1), (b, 1)):
                p, q = v(x, y, True), v(x, y + 1, True)
                pl, ql = v(x, y, False), v(x, y + 1, False)
                if out < 0:
                    faces += [(p, pl, ql), (p, ql, q)]
                else:
                    faces += [(p, ql, pl), (p, q, ql)]
    # walls along grid lines where the pixel above and below differ
    for line in range(h + 1):
        above = mask[line - 1] if line else np.zeros(w, bool)
        below = mask[line] if line < h else np.zeros(w, bool)
        xs = sorted(set(ends[line - 1] if line else []) | set(ends[line]))      # ends[h] is empty
        for x0, x1 in zip(xs, xs[1:]):
            m = (x0 + x1) // 2
            if above[m] == below[m]:
                continue
            p, q = v(x0, line, True), v(x1, line, True)
            pl, ql = v(x0, line, False), v(x1, line, False)
            if above[m]:      # filled on the image-above side (+Y), wall faces -Y
                faces += [(p, pl, ql), (p, ql, q)]
            else:             # faces +Y
                faces += [(p, ql, pl), (p, q, ql)]
    return np.array(verts, dtype=np.float64).reshape(-1, 3), np.array(faces, dtype=np.int64).reshape(-1, 3)


def write_stl(path, verts, faces):
    t = verts[faces].astype(np.float32)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n; rec["v"] = t
    with open(path, "wb") as f:
        f.write(b"layertone".ljust(80, b" "))
        f.write(struct.pack("<I", len(t)))
        rec.tofile(f)
