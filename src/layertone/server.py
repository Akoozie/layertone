"""The local page: `layertone-ui`, then open http://127.0.0.1:8765.

Plain standard-library HTTP server, no build step. The picture is
uploaded once and kept in memory; the page then asks for previews as the
sliders move, and for a 3MF when you export.
"""
import argparse
import base64
import hashlib
import io
import json
import tempfile
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from .filaments import load_library, save_library
from .optics import stack_colours
from .pipeline import export_3mf, export_flat_3mf, fit, flat_paint, open_image, render

PAGE = Path(__file__).with_name("static") / "index.html"
PREVIEW_PX_WIDE = 320           # preview resolution; export uses the real px
IMAGES = {}                     # id -> PIL image


def _png(img):
    b = io.BytesIO(); img.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def _settings(q):
    img = IMAGES[q["image"]]
    if not q.get("stack"):
        raise ValueError("Pick at least one filament")
    from .suggest import stack_filaments
    from .spools import check_stack
    fils = stack_filaments(q["stack"])
    if q.get("flat") and len(fils) > 4:
        raise ValueError("Flat Paint uses one AMS slot per colour: 4 at most")
    if not q.get("card"):
        check_stack(fils)
    crop = q.get("crop") or None
    return img, fils, float(q["width"]), int(q["base_layers"]), int(q["max_layers"]), crop


def _look(q):
    return (float(q.get("detail", 0)), float(q.get("brightness", 0)), float(q.get("contrast", 1)),
            float(q.get("smooth", 0)), int(q.get("colours", 0)))


def _clean(q, px):
    """Speck size in mm -> odd median window in pixels (0.6 mm at 0.2 mm px = 3)."""
    mm = float(q.get("speck", 0.6))
    return 2 * round(mm / px / 2) + 1 if mm else 0


def _block(q, px):
    mm = float(q.get("dither", 0))
    return max(1, round(mm / px)) if mm else 0


def _wall(q):
    """The page's Wall setting: None when off, else (wall text, join)."""
    wall = q.get("wall") or "off"
    return None if wall == "off" or q.get("flat") or q.get("card") else (wall, q.get("join") or "magnets")


def _thick(q, px):
    """Backing (mm) and frame (mm -> pixels) for render(). A wall's Backing is thick enough for its joins."""
    backing = float(q.get("backing", 0))
    if _wall(q):
        from .wall import wall_backing
        backing = wall_backing(backing, _wall(q)[1])
    return {
        "backing": backing,
        "frame": round(float(q.get("frame", 0)) / px),
        "frame_style": q.get("frame_style", "flat"),
        "px": px,
    }


def _wall_grid(q, width_mm, height_mm):
    """(cols, rows) for the wall, or the given ones even when the tiles would be too big (the page warns)."""
    from .wall import grid, parse, summary
    cols, rows = parse(_wall(q)[0])
    try:
        cols, rows = grid(width_mm, height_mm, cols, rows)
    except ValueError:
        cols, rows = cols or 1, rows or 1
    return cols, rows, summary(width_mm, height_mm, cols, rows, _wall(q)[1])


def _flat(q, rgb, fils, px):
    return flat_paint(rgb, fils, base_layers=0, paint_layers=int(q.get("flat_layers", 11)), speck=_clean(q, px) or 1)


def preview(q):
    img, fils, width, base, top, crop = _settings(q)
    rgb = fit(img, width, width / PREVIEW_PX_WIDE, crop, *_look(q))
    px = width / PREVIEW_PX_WIDE
    if q.get("flat"):
        res = _flat(q, rgb, fils, px)
        h, w = res.labels.shape
        return {"preview": _png(res.preview()), "colour_error": round(res.error(rgb), 1),
                "size_mm": [round(w * px, 1), round(h * px, 1)], "top_mm": round(res.top_z, 2), "flat": True,
                "corner_mm": 0,
                "start": asdict(fils[0]), "swaps": [], "thin_range": None,
                "parts": [asdict(f) for k, f in enumerate(fils) if (res.labels == k).any()],
                **_stand_fields(q, [w * px, h * px], res.top_z)}
    res = render(rgb, fils, base, top, clean=_clean(q, px), thin=int(q.get("thin", 0)), dither_block=_block(q, px),
                 swaps=q.get("swaps"), **_thick(q, px))
    h, w = res.heights.shape
    plan = res.plan
    wall, shown = None, res.preview()
    if _wall(q):
        from .wall import overlay
        cols, rows, wall = _wall_grid(q, w * px, h * px)
        wall["join"] = _wall(q)[1]
        wall["backing"] = plan.backing
        shown = overlay(shown, cols, rows) if cols * rows > 1 else shown
    if res.corner > 0:
        from .card import outline
        alpha = (outline((h, w), px, res.corner, soft=True) * 255).round().astype(np.uint8)
        shown = shown.convert("RGBA")
        shown.putalpha(Image.fromarray(alpha))
    every = stack_colours(plan.layers(), plan.filaments, plan.thickness())   # colour at each layer count
    return {
        # for the layer slider and 3D view: layers per pixel, and colour / top Z per layer count
        "heights": base64.b64encode(res.heights.astype("uint8").tobytes()).decode(),
        "shape": [h, w],
        "layer_hex": ["#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c) for c in every],
        "layer_z": [round(float(z), 3) for z in plan.z_top(range(1, plan.max_layers + 1))],
        "px_mm": px,
        "corner_mm": res.corner,
        "preview": _png(shown),
        "wall": wall,
        "colour_error": round(float(res.error), 1),
        "size_mm": [round(w * px, 1), round(h * px, 1)],
        "top_mm": round(float(res.z().max()), 2),
        "start": asdict(fils[0]),
        "swaps": [{"z": z, "layer": l, **asdict(f)} for z, l, f in zip(res.plan.swap_z(), res.plan.swaps, fils[1:])],
        **_spool_changes(plan),
        "thin_range": res.plan.thin_range(),
        "backing_range": res.plan.backing_range(),
        **({} if wall else _stand_fields(q, [w * px, h * px], float(res.z().max()))),
    }


def _spool_changes(plan):
    """Pauses for Stacks with more filaments than AMS slots: what to load first, and each spool swap."""
    from .spools import loading, pause_z
    ld = loading(plan.filaments, plan.swaps)
    return {"load": [f.name for f in ld.start] if ld.changes else None,
            "spool_changes": [{"z": pause_z(plan, c), "out": c.out.name, "into": c.into.name, "hex": c.into.hex}
                              for c in ld.changes]}


def suggestion(q):
    from .suggest import suggest
    img, fils, width, base, top, crop = _settings(q)
    rgb = fit(img, width, width / PREVIEW_PX_WIDE, crop, *_look(q))
    now, found = suggest(rgb, fils, base, top)
    return {"now": round(float(now), 2), "found": [
        {"error": round(float(e), 2), "owned": owned, "position": pos, **asdict(f)} for e, f, owned, pos in found]}


def suggestion_set(q):
    from .suggest import recommended, suggest_set, td_sources
    img, _, width, base, top, crop = _settings(dict(q, stack=q.get("stack") or ["black"]))
    rgb = fit(img, width, width / PREVIEW_PX_WIDE, crop, *_look(q))
    sets = suggest_set(rgb, base, top, most=int(q.get("most", 4)), owned_only=bool(q.get("owned_only")))
    src = td_sources()
    return {"recommended": recommended(sets), "sets": [
        {"error": round(e, 1), "filaments": [dict(asdict(f), owned=o, td_source=src.get(f.key, "guess"))
                                             for f, o in zip(fils, owned)]} for e, fils, owned in sets]}


def calibration_board(q):
    """The board for the Stack and swaps the preview is using now."""
    from .board import PX, board, chart
    img, fils, width, base, top, crop = _settings(q)
    rgb = fit(img, width, width / PREVIEW_PX_WIDE, crop, *_look(q))
    plan = render(rgb, fils, base, top, swaps=q.get("swaps")).plan
    res, levels = board(fils, plan.swaps, base, top)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "board.3mf"
        export_3mf(out, res, PX, "calibration board", "board.stl")
        data = out.read_bytes()
    return {"chart": _png(chart(res, levels)), "threemf": base64.b64encode(data).decode()}


def _card(q, px):
    from .card import CardSpec, make_card
    if not q.get("stack"):
        raise ValueError("Pick at least one filament")
    finish = _finish(q)
    if q.get("card_svg"):
        from .card import INLAY_STROKE, MIN_STROKE, svg_card
        return svg_card(q["card_svg"], q["stack"], px=px, min_stroke=INLAY_STROKE if finish == "inlay" else MIN_STROKE,
                        engrave=finish == "engrave", thickness=0.6 if finish == "engrave" else 0.8)
    pic = None
    if q.get("card_picture", "none") != "none" and q.get("image"):
        pic = IMAGES[q["image"]]
        if q.get("crop"):
            pic = pic.crop(tuple(q["crop"]))
    spec = CardSpec(lines=str(q.get("card_lines", "")).splitlines(), stack=q["stack"],
                    background=int(q.get("card_face", 0)), ink=int(q.get("card_ink", -1)),
                    accent=int(q.get("card_accent", 1)), qr=str(q.get("card_qr", "")).strip(), picture=pic,
                    picture_mode="logo" if q.get("card_picture") == "logo" else "photo",
                    rule=bool(int(q.get("card_rule", 1))), border=float(q.get("card_border", 0)))
    if finish == "engrave":
        from .card import engraved
        spec = engraved(spec)
    return make_card(spec, px)


def _finish(q):
    """inlay (smooth, face down; default), engrave (face up, cut in, one swap) or relief.
    A layered photo needs heights, so it is always relief."""
    photo = q.get("card_picture", "none") == "photo" and q.get("image") and not q.get("card_svg")
    f = q.get("card_finish") or ("relief" if int(q.get("card_relief", 0)) else "inlay")
    return "relief" if photo else f


def _relief(q):
    return _finish(q) != "inlay"


def card_preview(q):
    from .card import CARD_MM, inlay_card, plate_layout
    card = _card(q, 0.1)
    copies = len(plate_layout(int(q.get("card_copies", 8))))
    if not _relief(q):
        ic = inlay_card(card)
        return {"preview": _png(ic.preview()), "card": True, "inlay": True, "size_mm": list(CARD_MM),
                "top_mm": ic.thickness, "face_mm": ic.thickness, "depth_mm": ic.depth, "copies": copies,
                "warnings": ic.warnings, "body": asdict(ic.filaments[0]), "inlays": [asdict(f) for f in ic.filaments[1:]]}
    plan = card.plan
    return {"preview": _png(card.preview()), "card": True, "size_mm": list(CARD_MM),
            "top_mm": round(float(card.z.max()), 2), "face_mm": round(float(card.z.min()), 2),
            "copies": copies, "warnings": card.warnings,
            "start": asdict(plan.filaments[0]), "backing": plan.backing,
            "swaps": [{"z": z, "layer": l, **asdict(f)} for z, l, f in zip(plan.swap_z(), plan.swaps, plan.filaments[1:])]}


def _stand_fields(q, size_mm, top_mm):
    style = q.get("stand", "none")
    if style == "none":
        return {}
    from .stand import stand_size
    return {"stand_mm": stand_size(size_mm[0], size_mm[1], top_mm, style)}


def stand(q):
    """The stand as its own 3MF, sized from the print the page last previewed."""
    from .stand import make_stand, write_stand_3mf
    style = q.get("stand", "none")
    w, h = (float(v) for v in q["size_mm"])
    verts, faces = make_stand(w, h, float(q["top_mm"]), style)
    name = ((q.get("title") or "layertone").strip() or "layertone") + "_stand"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.3mf"
        write_stand_3mf(out, verts, faces, q.get("stand_filament") or "jade_white", title=f"{name} ({style})")
        return out.read_bytes(), name


def export(q):
    if q.get("card"):
        from .card import export_card_3mf, export_inlay_3mf, inlay_card
        name = (q.get("title") or "business_card").strip() or "business_card"
        card = _card(q, 0.08)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.3mf"
            if _relief(q):
                export_card_3mf(out, card, int(q.get("card_copies", 8)), name, name + ".stl")
            else:
                export_inlay_3mf(out, inlay_card(card), int(q.get("card_copies", 8)), name, name + ".stl")
            return out.read_bytes(), name
    img, fils, width, base, top, crop = _settings(q)
    px = float(q.get("px", 0.2))
    name = (q.get("title") or "layertone").strip() or "layertone"
    if q.get("flat"):
        res = _flat(q, fit(img, width, px, crop, *_look(q)), fils, px)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.3mf"
            export_flat_3mf(out, res, px, name, name + ".stl")
            return out.read_bytes(), name
    res = render(fit(img, width, px, crop, *_look(q)), fils, base, top, clean=_clean(q, px),
                 thin=int(q.get("thin", 0)), dither_block=_block(q, px), swaps=q.get("swaps"), **_thick(q, px))
    name = (q.get("title") or "layertone").strip() or "layertone"
    mask = None
    if res.corner > 0:
        from .card import outline
        mask = outline(res.heights.shape, px, res.corner)
    if _wall(q):
        from .wall import wall_zip
        h, w = res.heights.shape
        cols, rows, info = _wall_grid(q, (w - 1) * px, (h - 1) * px)
        if info["warning"]:
            raise ValueError(info["warning"])
        return wall_zip(res, px, cols, rows, _wall(q)[1], name, mask=mask), name + "_wall.zip"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.3mf"
        export_3mf(out, res, px, name, name + ".stl", mask=mask)
        return out.read_bytes(), name


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        if self.path == "/":
            self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/vendor/"):
            vendor = (PAGE.parent / "vendor").resolve()
            f = (PAGE.parent / self.path.lstrip("/")).resolve()
            if f.parent == vendor and f.is_file():
                self._send(f.read_bytes(), "text/javascript" if f.suffix == ".js" else "text/plain")
            else:
                self._send(b"not found", "text/plain", 404)
        elif self.path == "/api/filaments":
            self._json({k: asdict(f) for k, f in load_library().items()})
        else:
            self._send(b"not found", "text/plain", 404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            if self.path == "/api/image":
                key = hashlib.sha1(body).hexdigest()[:12]
                img = open_image(io.BytesIO(body))
                IMAGES[key] = img
                self._json({"image": key, "pixels": list(img.size)})
            elif self.path == "/api/filaments":
                lib = save_library(json.loads(body))
                self._json({k: asdict(f) for k, f in lib.items()})
            elif self.path == "/api/board":
                self._json(calibration_board(json.loads(body)))
            elif self.path == "/api/suggest_set":
                self._json(suggestion_set(json.loads(body)))
            elif self.path == "/api/suggest":
                self._json(suggestion(json.loads(body)))
            elif self.path == "/api/card":
                self._json(card_preview(json.loads(body)))
            elif self.path == "/api/preview":
                self._json(preview(json.loads(body)))
            elif self.path in ("/api/export", "/api/stand"):
                data, name = (export if self.path == "/api/export" else stand)(json.loads(body))
                zipped = name.endswith(".zip")
                self._send(data, "application/zip" if zipped else "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
                           extra={"Content-Disposition": f'attachment; filename="{name if zipped else name + ".3mf"}"'})
            else:
                self._send(b"not found", "text/plain", 404)
        except KeyError:
            self._json({"error": "The app restarted; choose the picture again"}, 400)
        except (ValueError, SystemExit) as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:             # keep the page alive, show what broke
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def log_message(self, *a):
        pass


def main(argv=None):
    p = argparse.ArgumentParser(prog="layertone-ui")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on; 0.0.0.0 lets a phone on the same network (or Tailscale) open the page")
    a = p.parse_args(argv)
    url = f"http://127.0.0.1:{a.port}"
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"layertone page at {url}  (Ctrl+C to stop)")
    if a.host != "127.0.0.1":
        import socket
        print(f"from another device: http://{socket.gethostbyname(socket.gethostname())}:{a.port}")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
