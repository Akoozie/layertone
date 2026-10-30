import numpy as np
from layertone.filaments import load_library, pick
from layertone.mesh import heightfield_mesh
from layertone.plan import Plan, best_plan, heights
from layertone.suggest import stack_filaments


def test_mesh_is_closed_and_outward():
    z = np.random.default_rng(0).uniform(0.5, 1.5, (12, 9))
    v, f = heightfield_mesh(z, 0.2)
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts == 2).all()                      # watertight
    t = v[f]
    vol = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6
    assert vol > 0                                  # normals face out
    assert np.isclose(vol, z[1:-1, 1:-1].mean() * 8 * 11 * 0.04, rtol=0.2)


def test_black_white_gets_brighter_with_height():
    fils = pick(["black", "jade_white"])
    plan = Plan(fils, [5], 5, 17, 0.2, 0.08)
    lum = plan.palette().mean(1)
    assert lum[0] < 0.15 and lum[-1] > 0.85
    assert (np.diff(lum) > 0).all()


def test_swap_z_matches_template():
    plan = Plan(pick(["black", "jade_white"]), [5], 5, 17, 0.2, 0.08)
    assert plan.swap_z() == [0.60]                  # the Alicia HueForge file


def test_gradient_plan_uses_full_range():
    rgb = np.repeat(np.linspace(0, 1, 50)[None, :, None], 3, 2).repeat(10, 0)
    plan, err = best_plan(rgb, pick(["black", "jade_white"]))
    n = heights(rgb, plan)
    assert n[:, 0].max() == 5 and n[:, -1].min() >= 15
    assert err < 10


def test_four_colour_plan_orders_swaps():
    rng = np.random.default_rng(1)
    rgb = rng.uniform(0, 1, (20, 20, 3))
    plan, _ = best_plan(rgb, stack_filaments(["black", "bambu_purple", "bambu_red", "jade_white"]))
    assert plan.swaps == sorted(plan.swaps) and len(set(plan.swaps)) == 3


def test_page_preview_and_export():
    from PIL import Image
    from layertone import server
    import base64
    img = Image.linear_gradient("L").convert("RGB").resize((60, 40))
    server.IMAGES["t"] = img
    q = {"image": "t", "stack": ["black", "jade_white"], "width": 30, "base_layers": 5, "max_layers": 17}
    d = server.preview(q)
    assert d["preview"].startswith("data:image/png") and d["swaps"][0]["z"] == 0.6
    h, w = d["shape"]
    assert len(base64.b64decode(d["heights"])) == h * w and len(d["layer_hex"]) == 17
    data, name = server.export({**q, "px": 0.5, "title": "grad"})
    assert data[:2] == b"PK" and name == "grad"


def test_flat_areas_become_few_triangles():
    z = np.full((200, 300), 0.6); z[50:150, 100:200] = 1.48
    v, f = heightfield_mesh(z, 0.2)
    assert len(f) < 2000                            # a full grid would be ~120k
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    assert (np.unique(edges, axis=0, return_counts=True)[1] == 2).all()


def test_thin_layers_fill_the_shadow_gap():
    import zipfile
    from layertone.optics import srgb_to_lab
    fils = pick(["black", "jade_white"])
    L = lambda p: srgb_to_lab(p.palette())[:, 0]
    plain, thin = Plan(fils, [5], 5, 17, 0.2, 0.08), Plan(fils, [5], 5, 17, 0.2, 0.08, thin=6)
    assert L(thin)[1] - L(thin)[0] < L(plain)[1] - L(plain)[0]     # smaller first step
    assert thin.swap_z() == [0.56] and thin.thin_range() == (0.52, 0.76)
    rgb = np.repeat(np.linspace(0, 1, 60)[None, :, None], 3, 2).repeat(40, 0)
    from layertone.pipeline import render, export_3mf
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "t.3mf"
        export_3mf(out, render(rgb, fils, thin=6), 0.5, "t", "t.stl")
        z = zipfile.ZipFile(out)
        assert 'min_z="0.52" max_z="0.76"' in z.read("Metadata/layer_config_ranges.xml").decode()
        assert '"0.04"' in z.read("Metadata/project_settings.config").decode()


def test_tone_keeps_black_and_white():
    from layertone.pipeline import tone
    x = np.array([0.0, 0.5, 1.0])
    up, flat = tone(x, brightness=0.5), tone(x, contrast=0.5)
    assert up[0] == 0 and up[2] == 1 and up[1] > 0.5
    assert np.allclose(flat, [0.25, 0.5, 0.75])


def test_swatch_reading_gives_td():
    from layertone.swatch import swatch, td_from_match
    plan, n = swatch(*pick(["black", "jade_white"]), bars=10)
    assert n.min() == 5 and n.max() == 55
    # a filament with that TD hides ~95 % at the matched bar
    from layertone.optics import layer_alpha
    td = td_from_match(12)
    assert abs(layer_alpha(12 * 2 * 0.08, td) - 0.95) < 0.01


def test_dither_keeps_average_and_block_size():
    from layertone.plan import dither
    f = np.tile(np.linspace(5, 9, 80), (40, 1))
    n = dither(f, block=2)
    assert abs(n.mean() - f.mean()) < 0.05
    assert (n[::2, ::2] == n[1::2, 1::2]).all()        # 2x2 dots


def test_manual_swaps_are_kept():
    import pytest
    from layertone.pipeline import render
    rgb = np.linspace(0, 1, 64)[None, :, None].repeat(8, 0).repeat(3, 2)
    fils = pick(["black", "jade_white"])
    res = render(rgb, fils, swaps=[9])
    assert res.plan.swaps == [9]
    with pytest.raises(ValueError):
        render(rgb, fils, swaps=[2])


def test_reduce_colours_keeps_k():
    from layertone.pipeline import reduce_colours
    rgb = np.random.default_rng(0).random((40, 40, 3))
    out = reduce_colours(rgb, 5)
    assert len(np.unique(out.reshape(-1, 3), axis=0)) <= 5
    assert abs(out.mean() - rgb.mean()) < 0.02


def test_filament_library_edit(tmp_path):
    import pytest
    from layertone.filaments import save_library, load_library
    p = tmp_path / "f.json"
    lib = save_library({"Grey PLA": {"name": "Grey", "hex": "#808080", "td": 2, "slot": 1}}, p)
    assert lib["grey_pla"].td == 2.0 and load_library(p)["grey_pla"].hex == "#808080"
    with pytest.raises(ValueError):
        save_library({"x": {"name": "x", "hex": "red", "td": 1, "slot": 1}}, p)


def test_suggest_finds_a_missing_colour():
    from layertone.suggest import suggest
    from layertone.filaments import Filament
    rgb = np.zeros((20, 40, 3)); rgb[:, :20] = [0.8, 0.1, 0.1]; rgb[:, 20:] = 1.0
    now, found = suggest(rgb, pick(["black", "jade_white"]), top=3, sample=20)
    assert found and found[0][0] < now and "red" in found[0][1].name.lower()


def test_flat_paint_parts_are_closed(tmp_path):
    from collections import Counter
    from layertone.pipeline import flat_paint, export_flat_3mf
    rgb = np.ones((30, 40, 3)); rgb[5:20, 5:25] = 0.05; rgb[10:28, 20:35] = [0.8, 0.15, 0.1]
    res = flat_paint(rgb, stack_filaments(["black", "jade_white", "bambu_red"]))
    assert set(np.unique(res.labels)) == {0, 1, 2}
    parts = export_flat_3mf(tmp_path / "f.3mf", res, 0.5, "f", "f.stl")
    vol = 0
    for v, f, fil in parts:
        e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        c = Counter(map(tuple, e))
        assert all(c.get((b, a), 0) == n for (a, b), n in c.items())      # closed, consistently wound
        t = v[f]; vol += np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6
    assert abs(vol - 30 * 40 * 0.25 * res.top_z) < 1e-6                  # parts tile the picture


def test_calibration_board_has_every_height():
    from layertone.board import board
    res, levels = board(pick(["black", "jade_white"]))
    assert levels == list(range(6, 18))
    assert set(np.unique(res.heights)) == set(range(5, 18))


def test_suggest_set_builds_a_stack_for_a_colour_picture():
    from layertone.suggest import recommended, suggest_set
    rgb = np.ones((16, 32, 3)); rgb[:, :10] = 0.05; rgb[:, 10:20] = [0.1, 0.3, 0.8]
    sets = suggest_set(rgb, most=3)
    assert [len(f) for _, f, _ in sets] == [2, 3]
    err, fils, owned = sets[recommended(sets)]
    assert err < sets[0][0] + 1e-9 and any(f.rgb[2] > f.rgb[0] + 0.3 for f in fils)   # a blue made it in


def test_stack_filaments_gives_bought_ones_free_slots():
    from layertone.suggest import stack_filaments
    fils = stack_filaments(["black", "pm_peach", "jade_white"])     # black is slot 2, jade white slot 3
    assert [f.slot for f in fils] == [2, 1, 3]


def test_backing_raises_everything_without_changing_colours(tmp_path):
    import zipfile
    from layertone.pipeline import render, export_3mf
    rgb = np.linspace(0, 1, 40 * 30).reshape(30, 40, 1).repeat(3, 2)
    a = render(rgb, pick(["black", "jade_white"]), clean=0)
    b = render(rgb, pick(["black", "jade_white"]), clean=0, backing=1.0, frame=3)
    assert np.allclose(a.plan.palette(), b.plan.palette())
    assert np.isclose(b.z()[3:-3, 3:-3].min() - a.z().min(), 1.0) and b.heights.shape == (36, 46)
    assert (b.heights[0] == b.plan.max_layers).all()
    assert np.isclose(b.plan.swap_z()[0] - a.plan.swap_z()[0], 1.0)
    export_3mf(tmp_path / "b.3mf", b, 0.5, "b", "b.stl")
    xml = zipfile.ZipFile(tmp_path / "b.3mf").read("Metadata/layer_config_ranges.xml").decode()
    assert 'min_z="0.20" max_z="1.20"' in xml and ">0.2<" in xml


def test_business_card_text_is_crisp_and_stroke_safe(tmp_path):
    from PIL import ImageFilter, Image
    from layertone.card import CardSpec, MIN_STROKE, export_card_3mf, level, make_card
    px = 0.08
    card = make_card(CardSpec(["Alex Doe", "Maker", "alex@example.com"], ["jade_white", "blue", "black"]), px)
    plan = card.plan
    assert plan.backing > 0 and 1.2 <= plan.z_top(plan.base_layers) < 1.4     # sturdy card face
    ink = card.z > plan.z_top(level(plan, 1)) + 0.01                           # the black text
    assert 0.02 < ink.mean() < 0.3
    # nearly all ink survives an opening the size of one nozzle line: no hair-thin strokes
    k = 2 * round(0.8 * MIN_STROKE / px / 2) + 1
    m = Image.fromarray(ink.astype(np.uint8) * 255)
    kept = np.asarray(m.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))) > 127
    assert kept.sum() / ink.sum() > 0.9
    out = tmp_path / "c.3mf"
    tris = export_card_3mf(out, make_card(CardSpec(["Alex"], ["black", "jade_white"]), 0.25), copies=8)
    assert out.read_bytes()[:2] == b"PK" and tris < 200_000


def test_business_card_qr_and_overflow():
    import pytest
    from layertone.card import CardSpec, make_card, qr_matrix, QR_MODULE
    url = "https://github.com/Akoozie/layertone"
    px = 0.25
    card = make_card(CardSpec(["Alex"], ["jade_white", "black"], qr=url), px)
    m = qr_matrix(url)
    side = (len(m) + 4) * QR_MODULE
    x0, y0 = 85 - 5 - side, (55 - side) / 2
    centres = (np.arange(len(m)) + 2.5) * QR_MODULE
    zs = card.z[((y0 + centres) / px).astype(int)][:, ((x0 + centres) / px).astype(int)]
    assert ((zs > card.z.min() + 0.1) == m).all()                 # every module raised in black, no others
    with pytest.raises(ValueError):
        make_card(CardSpec(["A very long name that will never fit on one card line at all"], qr=url), 0.25)


def test_business_card_from_svg_layout():
    from layertone.card import level, svg_card
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="55mm" viewBox="0 0 85 55">'
           '<rect width="85" height="55" fill="#ffffff"/><rect x="5" y="5" width="20" height="10" fill="#0a4a99"/>'
           '<rect x="40" y="30" width="30" height="0.3" fill="#000000"/></svg>')
    px = 0.2
    card = svg_card(svg, ["black", "blue", "jade_white"], px=px)
    plan = card.plan
    assert [f.key for f in plan.filaments] == ["jade_white", "black", "blue"]   # face first, small details lowest
    assert np.isclose(card.z[50, 75], plan.z_top(level(plan, 2)))             # blue panel at its band top
    assert np.isclose(card.z[200, 50], card.z.min())                           # the white face
    cov = (card.z[:, 275] - card.z.min()) / (plan.z_top(level(plan, 1)) - card.z.min())
    assert cov.sum() * px >= 0.45 - 1e-6                                              # 0.3 mm hairline thickened


def test_card_has_rounded_corners_cut_into_a_closed_mesh(tmp_path):
    from layertone.card import CORNER, CardSpec, make_card
    from layertone.mesh import heightfield_mesh
    card = make_card(CardSpec(["Alex"], ["jade_white", "black"]), 0.25)
    v, f = heightfield_mesh(card.z, card.px, mask=card.mask())
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts == 2).all()                                   # still watertight
    xy = v[:, :2]
    assert not ((xy[:, 0] < CORNER * 0.25) & (xy[:, 1] < CORNER * 0.25)).any()     # corner cut away
    assert np.asarray(card.preview())[0, 0, 3] == 0               # and transparent in the preview


def test_smooth_card_inlays_flush_and_mirrored(tmp_path):
    from layertone.card import CardSpec, export_inlay_3mf, inlay_card, make_card
    from layertone.mesh import mask_mesh
    ic = inlay_card(make_card(CardSpec(["Alex"], ["black", "jade_white"]), 0.25))
    assert [f.key for f in ic.filaments] == ["black", "jade_white"]            # body = the card colour
    assert 0.8 <= ic.depth <= 1.16 and ic.thickness > ic.depth                # deep enough for white over black
    assert ic.layers() == [0.2] + [0.16] * 4                                   # 0.16 mm layers: half the swaps of 0.08
    cols = (ic.labels == 1).nonzero()[1]
    assert cols.mean() < ic.labels.shape[1] / 2                                # text on the left from the front...
    parts = export_inlay_3mf(tmp_path / "c.3mf", ic, copies=1)
    assert parts < 200_000 and (tmp_path / "c.3mf").read_bytes()[:2] == b"PK"
    import json, zipfile
    d = json.loads(zipfile.ZipFile(tmp_path / "c.3mf").read("Metadata/project_settings.config"))
    assert d["layer_height"] == "0.16" and d["curr_bed_type"] == "Textured PEI Plate"     # the plate the A1 ships with
    v, f = mask_mesh((ic.labels == 1)[:, ::-1], ic.px, 0, ic.depth)            # ...and on the right in the file
    assert v[:, 0].mean() > 85 / 2 and v[:, 2].max() == ic.depth               # flush: no taller than the front layers


def test_engraved_card_is_one_swap_with_text_cut_in():
    from layertone.card import CardSpec, engraved, make_card
    spec = CardSpec(["Alex"], ["jade_white", "black"], background=0, ink=1)
    card = make_card(engraved(spec), 0.25)                                   # dark top by default
    plan = card.plan
    assert [f.key for f in plan.filaments] == ["jade_white", "black"] and len(plan.swaps) == 1
    face = np.median(card.z)
    assert np.isclose(face, card.z.max()) and 0.3 < face - card.z.min() < 0.5  # face on top, shallow grooves
    assert 0.9 <= card.z.max() <= 1.15                                        # about a 1 mm card
    light = make_card(engraved(spec, dark_top=False), 0.25)
    assert [f.key for f in light.plan.filaments] == ["black", "jade_white"] and light.z.max() > 1.3


def test_3mf_lists_only_the_stack_filaments_in_print_order(tmp_path):
    import json, re, zipfile
    from layertone.card import CardSpec, export_card_3mf, make_card
    out = tmp_path / "c.3mf"
    export_card_3mf(out, make_card(CardSpec(["Alex"], ["black", "jade_white"]), 0.25), copies=1)
    z = zipfile.ZipFile(out)
    d = json.loads(z.read("Metadata/project_settings.config"))
    assert d["filament_colour"] == d["filament_multi_colour"] == ["#161616", "#FFFFFF"]
    assert d["filament_settings_id"] == ["Generic PLA High Speed @BBL A1", "Bambu PLA Basic @BBL A1"]
    assert len(d["nozzle_temperature"]) == 2 and len(d["flush_volumes_matrix"]) == 4
    assert len(d["printable_area"]) == 4                                   # bed corners, not filaments
    assert re.findall(r'extruder="(\d)"', z.read("Metadata/custom_gcode_per_layer.xml").decode()) == ["2"]
    ms = z.read("Metadata/model_settings.config").decode()
    assert 'key="extruder" value="1"' in ms and 'key="filament_maps" value="1 1"' in ms


def test_relief_mesh_is_not_mirrored():
    """Image top-left must land at the back left of the plate (low X, high Y), as seen from above."""
    z = np.ones((50, 80)); z[:10, :10] = 3
    mask = np.ones(z.shape, bool); mask[:5, :5] = False      # a cut at the top-left corner too
    v, _ = heightfield_mesh(z, 1.0, 0.01, mask=mask)
    hi = v[v[:, 2] > 2.5]
    assert hi[:, 0].max() <= 10 and hi[:, 1].min() >= 39
    assert not ((v[:, 0] < 4) & (v[:, 1] > 45)).any()          # nothing left in the cut corner


def test_engraved_card_reads_the_right_way_up():
    """A groove drawn at the card's top-left must be cut at the back left of the plate, seen from above."""
    from layertone.card import svg_card
    from layertone.mesh import heightfield_mesh
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="55mm" viewBox="0 0 85 55">'
           '<rect width="85" height="55" fill="#FFFFFF"/><rect x="8" y="6" width="10" height="4" fill="#161616"/></svg>')
    card = svg_card(svg, ["black", "jade_white"], px=0.25, engrave=True, thickness=0.6)
    assert not card.warnings
    v, _ = heightfield_mesh(card.z, card.px, 0.02, mask=card.mask())
    groove = v[(v[:, 2] > 0.1) & (v[:, 2] < card.z.max() - 0.1)]
    assert len(groove) and groove[:, 0].max() < 20 and groove[:, 1].min() > 55 - 12


def test_engraved_svg_warns_about_small_text():
    from layertone.card import svg_card
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="85mm" height="55mm" viewBox="0 0 85 55">'
           '<rect width="85" height="55" fill="#161616"/>'
           '<text x="6" y="20" font-size="{}" font-weight="700" fill="#FFFFFF">ABC</text></svg>')
    assert any("cap height" in w for w in svg_card(svg.format(4), ["jade_white", "black"], px=0.25, engrave=True).warnings)
    assert not any("cap height" in w for w in svg_card(svg.format(7.5), ["jade_white", "black"], px=0.25, engrave=True).warnings)


def test_stand_sizes_match_the_tuned_stands():
    from layertone.stand import plain_settings, contour_settings
    assert plain_settings(120, 89.8, 2.48) == dict(thick=2.48, length=120, depth=28, h_front=5, h_back=12,
                                                   lean=12, y_mouth=14, slot_depth=6)
    assert plain_settings(132.8, 199.4, 1.48) == dict(thick=1.48, length=133, depth=40, h_front=7, h_back=16,
                                                      lean=10, y_mouth=15, slot_depth=8)
    assert contour_settings(132.8, 199.4, 1.48) == dict(thick=1.48, sx=1.0, sy=1.0)
    assert contour_settings(400, 400, 2)["sx"] * 195.1 <= 250          # stays on the A1 bed


def test_plain_stand_is_closed_with_slot_for_the_print():
    import pytest
    pytest.importorskip("manifold3d")
    from layertone.stand import make_stand
    v, f = make_stand(100, 75, 2.0, "plain")
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts == 2).all()
    assert np.allclose(v.min(0)[[0, 2]], [-50, 0]) and np.isclose(v.max(0)[0], 50)
    assert np.isclose(v.max(0)[2], 12)                          # small prints get the 120 mm stand's bar


def _closed(f):
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return (counts == 2).all()


def test_wall_tiles_share_edges_and_reassemble():
    from layertone.wall import grid, split
    h = np.random.default_rng(0).integers(0, 9, (41, 61))
    tiles = split(h, 3, 2)
    assert [t.name for t in tiles] == ["A1", "A2", "A3", "B1", "B2", "B3"]
    out = np.full_like(h, -1)
    for t in tiles:
        out[t.y0:t.y0 + t.heights.shape[0], t.x0:t.x0 + t.heights.shape[1]] = t.heights
    assert (out == h).all()                                        # nothing lost, no gap
    assert (tiles[0].heights[:, -1] == tiles[1].heights[:, 0]).all()   # shared edge column
    assert (tiles[0].heights[-1] == tiles[3].heights[0]).all()         # shared edge row
    assert grid(450, 337) == (2, 2) and grid(200, 100) == (1, 1) and grid(600, 200, rows=2) == (3, 2)


def test_wall_grid_refuses_tiles_bigger_than_the_bed():
    import pytest
    from layertone.wall import grid, summary
    with pytest.raises(ValueError):
        grid(600, 300, cols=2, rows=1)
    s = summary(600, 300, 2, 1, "magnets")
    assert s["warning"] and s["tile_mm"] == [300, 300]


def test_wall_backing_keeps_cover_over_the_cuts():
    from layertone.wall import COVER, DEPTH, wall_backing
    assert wall_backing(1.0, "magnets") >= DEPTH["magnets"] + COVER - 1e-9
    assert wall_backing(1.0, "none") >= 1.0 and wall_backing(5.0, "magnets") == 5.0


def test_wall_joins_pair_up_across_every_seam():
    from layertone.wall import join_count, seam_spots, split
    spots = seam_spots(169)
    assert len(spots) >= 2 and all(0 < v < 169 for v in spots)
    assert join_count(2, 2, 225, 169) == 2 * len(seam_spots(169)) + 2 * len(seam_spots(225))   # a seam in each direction, two tiles long
    assert join_count(1, 1, 200, 150) == 0


def test_wall_tile_is_closed_with_pockets_and_a_label():
    import pytest
    pytest.importorskip("manifold3d")
    from layertone.pipeline import render
    from layertone.suggest import stack_filaments
    from layertone.wall import split, tile_mesh, wall_backing
    px = 1.0
    rgb = np.tile(np.linspace(0, 1, 60)[None, :, None], (40, 1, 3))
    res = render(rgb, stack_filaments(["black", "jade_white"]), 2, 6, backing=wall_backing(0, "magnets"))
    t = split(res.heights, 2, 1)[0]                              # has a right side, so pockets
    for join in ("magnets", "keys", "plates", "none"):
        v, f = tile_mesh(t, res.plan, px, join, 2, 1, 0.03)
        assert _closed(f), join
        assert np.isclose(v[:, 2].min(), 0, atol=1e-5) and v[:, 0].max() <= 30.0 + 1e-6
    plain = tile_mesh(t, res.plan, px, "none", 2, 1, 0.03)[1]
    assert len(tile_mesh(t, res.plan, px, "magnets", 2, 1, 0.03)[1]) > len(plain)   # pockets add faces


def test_magnet_pocket_leaves_a_5mm_gap_between_ribs():
    import pytest
    pytest.importorskip("manifold3d")
    from layertone.wall import magnet_pocket
    p = magnet_pocket()
    cs = p.slice(1.0)
    pts = np.vstack([np.asarray(q) for q in cs.to_polygons()])
    r = np.hypot(pts[:, 0], pts[:, 1])
    assert np.isclose(r.max(), 2.7, atol=0.03)                    # 5.4 bore
    diag = pts[np.isclose(np.abs(pts[:, 0]), np.abs(pts[:, 1]), atol=0.05)]
    assert np.isclose(np.hypot(diag[:, 0], diag[:, 1]).min(), 2.5, atol=0.05)   # ribs at 45 deg leave 5.0
    assert np.isclose(p.bounding_box()[5], 2.2)                   # 2.2 deep


def test_page_wall_preview_and_zip_export():
    import io, zipfile
    from layertone import server
    from PIL import Image
    buf = io.BytesIO(); Image.fromarray((np.linspace(0, 255, 96 * 64).reshape(64, 96, 1) * [[[1, 1, 1]]]).astype("uint8")).save(buf, "PNG")
    q = {"image": "wall-test", "stack": ["black", "jade_white"], "width": 400, "base_layers": 3, "max_layers": 6,
         "wall": "2x2", "join": "magnets", "px": 4.0, "backing": 1}
    server.IMAGES["wall-test"] = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    d = server.preview(q)
    assert d["wall"]["cols"] == 2 and d["wall"]["rows"] == 2 and not d["wall"]["warning"] and d["wall"]["joins"] > 0
    assert d["top_mm"] >= 2.8 + 0.2                                # wall backing, not the 1 mm asked for
    data, name = server.export(q)
    assert name == "layertone_wall.zip"
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert {"layertone_A1.3mf", "layertone_B2.3mf", "layertone_joins.3mf", "layertone_layout.png"} <= set(names)
    q["wall"], q["width"] = "2x1", 800
    assert server.preview(q)["wall"]["warning"]                    # 400 mm tiles do not fit the A1


def test_cli_corner_rounds_a_picture_relief(tmp_path):
    from PIL import Image
    from layertone.cli import main
    src = tmp_path / "pic.png"
    Image.fromarray((np.linspace(0, 255, 40 * 56).reshape(56, 40)).astype(np.uint8)).convert("RGB").save(src)
    main([str(src), "--stack", "black,jade_white", "--width", "20", "--corner", "3", "--out", str(tmp_path / "r")])
    import zipfile, re
    t = zipfile.ZipFile(tmp_path / "r.3mf").read("3D/Objects/object_1.model").decode()
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)"', t), float)
    v -= v.min(0)
    assert np.hypot(v[:, 0], v[:, 1]).min() > 0.8         # the corner is cut away, not square


def _five():
    return stack_filaments(["black", "jade_white", "blue", "bambu_red", "bambu_yellow"])


def test_fifth_filament_swaps_the_spool_not_printing_and_needed_last():
    from layertone.spools import loading
    fils = _five()
    ld = loading(fils, [5, 8, 10, 13])
    assert ld.lanes == [1, 2, 3, 4, 1] and [f.key for f in ld.start] == ["black", "jade_white", "blue", "bambu_red"]
    (c,) = ld.changes
    assert (c.out.key, c.into.key, c.lane) == ("black", "bambu_yellow", 1)
    assert c.pause_layer == 12                       # one layer before yellow starts, after black's last layer
    # a filament that comes back reuses its lane, no pause
    again = loading(pick(["black", "jade_white", "blue", "black"]), [5, 7, 9])
    assert again.lanes == [1, 2, 3, 1] and not again.changes


def test_spool_change_needs_a_free_layer_to_pause_on():
    from layertone.spools import check_stack, feasible
    import pytest
    assert not feasible(_five(), [5, 6, 7, 8])       # every layer up to yellow is a tool change
    assert feasible(_five(), [5, 6, 7, 9])
    with pytest.raises(ValueError):
        check_stack(pick(["black", "black"]))
    with pytest.raises(ValueError):
        check_stack(pick(["black", "jade_white"] * 5))
    rgb = np.random.default_rng(1).uniform(0, 1, (20, 30, 3))
    plan, _ = best_plan(rgb, _five(), 5, 12)
    assert feasible(_five(), plan.swaps)


def test_3mf_pauses_for_a_spool_change(tmp_path):
    import io, json, re, zipfile
    from PIL import Image
    from layertone.threemf import write_3mf
    plan = Plan(_five(), [5, 8, 10, 13], 5, 17, 0.2, 0.08)
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 1.0]]); f = np.array([[0, 1, 2]])
    write_3mf(tmp_path / "p.3mf", v, f, plan, Image.new("RGB", (8, 8), (255, 0, 0)), "t")
    z = zipfile.ZipFile(tmp_path / "p.3mf")
    codes = re.findall(r'top_z="([\d.]+)" type="(\d)" extruder="(\d)"[^>]*gcode="([^"]+)"',
                       z.read("Metadata/custom_gcode_per_layer.xml").decode())
    assert codes == [("0.60", "2", "2", "tool_change"), ("0.84", "2", "3", "tool_change"),
                     ("1.00", "2", "4", "tool_change"), ("1.16", "1", "4", "M400 U1"), ("1.24", "2", "1", "tool_change")]
    for n in z.namelist():                                    # no picture left over from the template
        if n.endswith(".png"):
            im = Image.open(io.BytesIO(z.read(n)))
            assert im.getpixel((im.width // 2, im.height // 2)) == (255, 0, 0), n
    d = json.loads(z.read("Metadata/project_settings.config"))
    assert len(d["filament_colour"]) == 4                     # the AMS lanes, not the 5 filaments
    fm = d["flush_volumes_matrix"]
    assert fm[3 * 4 + 0] == max(fm, key=float)                # purging into the swapped lane: the most


def test_despeckle_keeps_thin_lines_drops_specks():
    from layertone.plan import despeckle
    n = np.full((20, 20), 5)
    n[2, 1:19] = 17                          # a 1-pixel letter stroke
    n[12, 12] = 17                           # a lone speck
    n[15, 5] = 4                             # a lone pit
    n[7:9, 2:4] = 17                         # a 2x2 blob
    n[7:10, 10:13] = 17                      # a 3x3 blob
    a = despeckle(n, 3)
    assert (a[2, 1:19] == 17).all() and a[12, 12] == 5 and a[15, 5] == 5
    assert (a[7:9, 2:4] == 5).all() and (a[7:10, 10:13] == 17).all()
    b = despeckle(n, 5)
    assert (b[2, 1:19] == 17).all() and (b[7:10, 10:13] == 5).all()


def test_every_frame_style_renders_in_bounds():
    from layertone.filaments import pick
    from layertone.pipeline import FRAME_STYLES, render
    rgb = np.tile(np.linspace(0, 1, 40)[None, :, None], (30, 1, 3))
    fils = pick(["black", "blue", "jade_white"])
    plain = render(rgb, fils, base_layers=3, max_layers=10, frame=0, clean=0)
    for style in FRAME_STYLES:
        res = render(rgb, fils, base_layers=3, max_layers=10, frame=4, frame_style=style, clean=0)
        assert res.heights.shape == (38, 48)
        assert res.heights.min() >= res.plan.base_layers
        assert res.heights.max() <= res.plan.max_layers
        assert (res.heights[4:-4, 4:-4] == plain.heights).all()


def test_frame_style_height_profiles():
    import pytest
    from layertone.filaments import pick
    from layertone.pipeline import FRAME_STYLES, render
    rgb = np.tile(np.linspace(0, 1, 40)[None, :, None], (30, 1, 3))
    fils = pick(["black", "blue", "jade_white"])
    f = 15
    flat = render(rgb, fils, base_layers=5, max_layers=17, frame=f, frame_style="flat", clean=0)
    assert (flat.heights[:f, :] == flat.plan.max_layers).all()
    assert (flat.heights[-f:, :] == flat.plan.max_layers).all()
    assert (flat.heights[:, :f] == flat.plan.max_layers).all()
    assert (flat.heights[:, -f:] == flat.plan.max_layers).all()

    bevel = render(rgb, fils, base_layers=5, max_layers=17, frame=f, frame_style="bevel", clean=0)
    hi, lo = bevel.plan.max_layers, bevel.plan.base_layers
    mid_col = bevel.heights.shape[1] // 2
    assert bevel.heights[0, mid_col] == hi
    assert abs(bevel.heights[f - 1, mid_col] - lo) <= 1

    steps = render(rgb, fils, base_layers=5, max_layers=17, frame=f, frame_style="steps", clean=0)
    ring_mask = np.ones(steps.heights.shape, bool)
    ring_mask[f:-f, f:-f] = False
    k = len(fils) // 2
    mid = steps.plan.swaps[k]
    assert set(np.unique(steps.heights[ring_mask])) == {hi, mid, lo}

    with pytest.raises(ValueError):
        render(rgb, fils, frame=f, frame_style="unknown")


def test_rounded_frame_export_cuts_corners(tmp_path):
    import re, zipfile
    from layertone.card import outline
    from layertone.filaments import pick
    from layertone.pipeline import export_3mf, render
    rgb = np.tile(np.linspace(0, 1, 40)[None, :, None], (30, 1, 3))
    fils = pick(["black", "jade_white"])
    px = 0.5
    res = render(rgb, fils, frame=6, frame_style="rounded", px=px, clean=0)
    radius = res.corner
    assert radius == 3.0
    out = tmp_path / "rounded.3mf"
    mask = outline(res.heights.shape, px, radius)
    export_3mf(out, res, px, "test", "test.stl", mask=mask)
    t = zipfile.ZipFile(out).read("3D/Objects/object_1.model").decode()
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)"', t), float)
    v -= v.min(0)
    assert np.hypot(v[:, 0], v[:, 1]).min() > 0.8


def test_wall_rounded_cuts_only_outer_corners(tmp_path):
    import re, zipfile
    import pytest
    pytest.importorskip("manifold3d")
    from layertone.card import outline
    from layertone.filaments import pick
    from layertone.pipeline import render
    from layertone.wall import export_wall, wall_backing
    px = 1.0
    rgb = np.tile(np.linspace(0, 1, 40)[None, :, None], (20, 1, 3))
    fils = pick(["black", "jade_white"])
    res = render(rgb, fils, base_layers=2, max_layers=5, frame=6, frame_style="rounded",
                 backing=wall_backing(0, "none"), px=px, clean=0)
    radius = res.corner
    mask = outline(res.heights.shape, px, radius)
    export_wall(tmp_path, res, px, cols=2, rows=1, join="none", title="w", mask=mask)
    t1 = zipfile.ZipFile(tmp_path / "w_A1.3mf").read("3D/Objects/object_1.model").decode()
    v1 = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)"', t1), float)
    v1 -= v1.min(0)
    assert np.hypot(v1[:, 0], v1[:, 1]).min() > 1.0
    w1_mm = v1[:, 0].max()
    assert np.hypot(v1[:, 0] - w1_mm, v1[:, 1]).min() < 0.1


def test_server_preview_rounded_transparent_corners():
    import base64, io
    from layertone import server
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray((np.linspace(0, 255, 60 * 40).reshape(40, 60, 1) * [[[1, 1, 1]]]).astype("uint8")).save(buf, "PNG")
    server.IMAGES["preview-round-test"] = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    q = {"image": "preview-round-test", "stack": ["black", "jade_white"], "width": 100, "base_layers": 3,
         "max_layers": 6, "frame": 5, "frame_style": "rounded"}
    res = server.preview(q)
    assert res["corner_mm"] > 0
    header, b64data = res["preview"].split(",", 1)
    im = Image.open(io.BytesIO(base64.b64decode(b64data)))
    assert im.mode == "RGBA"
    arr = np.asarray(im)
    assert arr[0, 0, 3] == 0 and arr[0, -1, 3] == 0 and arr[-1, 0, 3] == 0 and arr[-1, -1, 3] == 0
    h, w = arr.shape[:2]
    assert arr[h // 2, w // 2, 3] == 255


def test_narrow_frame_band_profiles():
    import itertools
    from layertone.pipeline import frame_heights
    hi, mid, lo = 17, 10, 5
    for f in range(3, 9):
        if f >= 4:
            double_cs = frame_heights((1, 1), f, "double", lo, mid, hi)[:f, f].tolist()
            assert [k for k, _ in itertools.groupby(double_cs)] == [hi, lo, hi, lo]
        steps_cs = frame_heights((1, 1), f, "steps", lo, mid, hi)[:f, f].tolist()
        assert [k for k, _ in itertools.groupby(steps_cs)] == [hi, mid, lo]
        mat_cs = frame_heights((1, 1), f, "mat", lo, mid, hi)[:f, f].tolist()
        assert mat_cs[0] == hi and mat_cs[-1] == lo


def test_bevel_and_cove_hit_hi_and_lo():
    from layertone.pipeline import frame_heights
    hi, mid, lo = 17, 10, 5
    for f in (5, 10):
        for style, (want_out, want_in) in {"bevel": (hi, lo), "cove": (lo, hi)}.items():   # cove rises toward the picture
            h = frame_heights((1, 1), f, style, lo, mid, hi)
            outer = h[0, f]
            inner = h[f - 1, f]
            assert outer == want_out, f"{style} at f={f} outer pixel {outer} != {want_out}"
            assert inner == want_in, f"{style} at f={f} inner pixel {inner} != {want_in}"

