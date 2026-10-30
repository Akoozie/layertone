"""Write a Bambu Studio 3MF by filling a template project.

The template (templates/a1_0.08.3mf) came from a real HueForge export for the
A1, so its print settings carry over. We swap in the mesh, the thumbnails,
the project's filament list and one tool change per swap.

The filament list holds only the filaments the print uses, in the order it
needs them (filament 1 first), each with its own colour and the nearest preset
of the template's (eSUN PLA+, Generic PLA High Speed, Bambu PLA Basic). Bambu
Studio matches them to the AMS slots by colour when you print.
"""
import io
import json
import re
import zipfile
import numpy as np
from pathlib import Path
from PIL import Image

TEMPLATE = Path(__file__).parent / "templates" / "a1_0.08.3mf"
NOT_PER_FILAMENT = {"printable_area", "head_wrap_detect_zone"}    # 4-long lists that are corners, not filaments


def _preset_column(fil, presets):
    """The template filament whose preset fits `fil` best, by vendor in its name."""
    name = fil.name.lower()
    for i, p in enumerate(presets):
        if p.split()[0].lower() in name:
            return i
    return next((i for i, p in enumerate(presets) if p.startswith("Bambu PLA Basic")), 0)


def project_filaments(d, fils, swapped=()):
    """Rewrite project_settings `d` so its filament list is exactly `fils`.
    swapped: 1-based lanes whose spool changes mid-print; purging into them uses the most flush."""
    presets = d["filament_settings_id"]
    m = len(presets)
    cols = [_preset_column(f, presets) for f in fils]
    for k, v in list(d.items()):
        if isinstance(v, list) and len(v) == m and k not in NOT_PER_FILAMENT:
            d[k] = [v[c] for c in cols]
    n = len(fils)
    d["filament_colour"] = d["filament_multi_colour"] = [f.hex.upper() for f in fils]
    d["filament_self_index"] = [str(i + 1) for i in range(n)]
    d["filament_map"] = ["1"] * n
    fm = d["flush_volumes_matrix"]
    most = max(fm, key=float)
    d["flush_volumes_matrix"] = ["0" if a == b else (fm[ca * m + cb] if ca != cb and b + 1 not in swapped else most)
                                 for a, ca in enumerate(cols) for b, cb in enumerate(cols)]
    d["flush_volumes_vector"] = d["flush_volumes_vector"][:2 * n]
    dif = d["different_settings_to_system"]                         # process, one per filament, printer
    d["different_settings_to_system"] = [dif[0]] + [dif[1 + c] for c in cols] + [dif[-1]]
    return d


def _mesh_xml(parts):
    """parts: [(verts, faces)], one <object> each (ids 1..n)."""
    b = io.StringIO()
    b.write('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
            'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
            'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n')
    for i, (verts, faces) in enumerate(parts, 1):
        b.write(f'  <object id="{i}" p:UUID="{i:04x}0000-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <mesh>\n    <vertices>\n')
        b.write("".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n' for x, y, z in verts))
        b.write('    </vertices>\n    <triangles>\n')
        b.write("".join(f'     <triangle v1="{a}" v2="{c}" v3="{d}"/>\n' for a, c, d in faces))
        b.write('    </triangles>\n   </mesh>\n  </object>\n')
    b.write(' </resources>\n <build/>\n</model>\n')
    return b.getvalue().encode()


def _thumb(preview, size):
    im = preview.convert("RGB")
    im.thumbnail((size, size))
    c = Image.new("RGB", (size, size), (230, 230, 230))
    c.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    o = io.BytesIO(); c.save(o, "PNG"); return o.getvalue()


def write_3mf(out, verts, faces, plan, preview, title, name="layertone.stl", template=TEMPLATE):
    """One Stack relief: one part, a tool change per Swap. A Stack with more
    filaments than AMS slots also gets a pause before every Spool change
    (spools.py): the project filaments are then the AMS lanes."""
    from .spools import describe, loading, pause_z
    fils = plan.filaments
    ld = loading(fils, plan.swaps)
    swaps = list(zip(plan.swap_z(), fils[1:]))
    steps = ", ".join(f"{f.name} at {z:.2f} mm" for z, f in swaps)
    if ld.changes:
        steps += ". Spool changes (the print pauses): " + "; ".join(describe(plan))
    ranges = []
    if plan.backing_range():
        ranges.append((*plan.backing_range(), 0.2))
        steps += f". Backing layers {plan.backing_range()[0]:.2f}-{plan.backing_range()[1]:.2f} mm are 0.2 mm thick"
    if plan.thin_range():
        ranges.append((*plan.thin_range(), plan.thin_h))
        steps += f". Layers {plan.thin_range()[0]:.2f}-{plan.thin_range()[1]:.2f} mm are {plan.thin_h:g} mm thick"
    desc = (f"Made with layertone. 0.08 mm layers, 0.2 mm first layer, 100% infill. "
            f"Start in {fils[0].name}, then {steps}. Max height {verts[:, 2].max():.2f} mm.")
    codes = [(z, 2, ld.lanes[j], f.hex.upper(), "", "tool_change") for j, (z, f) in enumerate(swaps, 1)]
    codes += [(pause_z(plan, c), 1, ld.lanes[c.position - 1], "",
               _attr(f"Swap the {c.out.name} spool for {c.into.name}"), "M400 U1") for c in ld.changes]
    _write(out, [(verts, faces, fils[0])], ld.start, sorted(codes), desc, preview, title, name, template, ranges,
           swapped_lanes={c.lane for c in ld.changes})


def _attr(text):
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def write_flat_3mf(out, parts, preview, title, name="layertone.stl", template=TEMPLATE, layer_height=None, bed=None,
                   extra=None):
    """Flat Paint: one part per filament, each printed in its own filament.
    parts: [(verts, faces, filament)]. layer_height: mm, instead of the template's 0.08.
    bed: Bambu plate type, e.g. "High Temp Plate" (smooth PEI), instead of the textured plate.
    extra: project settings to set last, e.g. walls and infill for a solid part."""
    fils = [f for _, _, f in parts]
    desc = ("Made with layertone (Flat Paint). Every colour is its own part with its own filament; "
            "Bambu Studio swaps filament within each layer that has more than one. "
            + ", ".join(f"filament {i} {f.name}" for i, f in enumerate(fils, 1)) + ".")
    _write(out, parts, fils, [], desc, preview, title, name, template, layer_height=layer_height, bed=bed,
           extra=extra)


def _write(out, parts, fils, codes, desc, preview, title, name, template, ranges=(), layer_height=None, bed=None,
           extra=None, swapped_lanes=()):
    """fils: the project filaments (one per AMS lane). codes: [(top z, type, lane, colour, message, gcode)]
    for custom_gcode_per_layer.xml (type 2 = tool change, 1 = pause).
    ranges: [(bottom z, top z, layer height)] written as Bambu height range modifiers.
    swapped_lanes: lanes that get a Spool change; purges into them are the most the template uses."""
    allv = np.concatenate([v for v, _, _ in parts])
    lo, hi = allv.min(0), allv.max(0)
    shift = (lo + hi) / 2                  # Bambu stores objects centred on their origin
    half_h = (hi[2] - lo[2]) / 2
    n_faces = sum(len(f) for _, f, _ in parts)
    top_id = len(parts) + 1                # the object holding the parts comes after them, as Bambu writes it

    used = list(dict.fromkeys(f.key for f in fils))
    order = [next(f for f in fils if f.key == k) for k in used]
    idx = {k: i + 1 for i, k in enumerate(used)}      # project filament number, 1 = first printed

    zin = zipfile.ZipFile(template)
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        n = item.filename
        data = zin.read(n)
        if n == "3D/Objects/object_1.model":
            data = _mesh_xml([(v - shift, f) for v, f, _ in parts])
        elif n == "3D/3dmodel.model":
            s = data.decode()
            s = re.sub(r'<metadata name="(Title|Description)">.*?</metadata>\s*', "", s, flags=re.S)
            s = s.replace("<resources>", f'<metadata name="Title">{title}</metadata>\n '
                                         f'<metadata name="Description">{desc}</metadata>\n <resources>', 1)
            comp = re.search(r' *<component [^>]*/>\n', s).group(0)
            s = s.replace(comp, "".join(comp.replace('objectid="1"', f'objectid="{i}"')
                                        .replace("00010000-", f"{i:04x}0000-") for i in range(1, len(parts) + 1)))
            s = re.sub(r'(transform="1 0 0 0 1 0 0 0 1 128 128 )[\d.]+', rf'\g<1>{half_h:.4f}', s)
            s = s.replace('<object id="2"', f'<object id="{top_id}"').replace('objectid="2" p:UUID="00000002',
                                                                              f'objectid="{top_id}" p:UUID="00000002')
            data = s.encode()
        elif n == "Metadata/model_settings.config":
            s = data.decode()
            part = re.search(r' *<part id="1".*?</part>\n', s, flags=re.S).group(0)
            new_parts = ""
            for i, (_, f, fil) in enumerate(parts, 1):
                p = part.replace('<part id="1"', f'<part id="{i}"').replace(
                    'source_volume_id" value="0"', f'source_volume_id" value="{i - 1}"')
                p = re.sub(r'(key="name" value=")[^"]*', rf'\g<1>{fil.name if len(parts) > 1 else name}', p)
                p = re.sub(r'face_count="\d+"', f'face_count="{len(f)}"', p)
                if len(parts) > 1:
                    p = p.replace('<metadata key="matrix"', f'<metadata key="extruder" value="{idx[fil.key]}"/>\n      <metadata key="matrix"', 1)
                new_parts += p
            s = s.replace(part, new_parts)
            s = re.sub(r'(<object id="\d+">\s*<metadata key="name" value=")[^"]*', rf'\g<1>{name}', s)
            s = re.sub(r'(key="extruder" value=")\d+(?="/>\s*<metadata face_count)', rf'\g<1>{idx[fils[0].key]}', s)
            s = re.sub(r'(key="filament_maps" value=")[\d ]+', rf'\g<1>{" ".join(["1"] * len(order))}', s)
            s = re.sub(r'<metadata face_count="\d+"/>', f'<metadata face_count="{n_faces}"/>', s)
            s = re.sub(r'(source_offset_z" value=")[\d.]+', rf'\g<1>{half_h:.4f}', s)
            s = re.sub(r'(transform="1 0 0 0 1 0 0 0 1 [\d.]+ 0 )[\d.]+', rf'\g<1>{2 * half_h:.4f}', s)
            s = (s.replace('<object id="2">', f'<object id="{top_id}">')
                  .replace('key="object_id" value="2"', f'key="object_id" value="{top_id}"')
                  .replace('object_id="2"', f'object_id="{top_id}"'))
            data = s.encode()
        elif n == "Metadata/custom_gcode_per_layer.xml":
            lines = "".join(f'<layer top_z="{z:.2f}" type="{t}" extruder="{lane}" color="{c}" '
                            f'extra="{msg}" gcode="{g}"/>\n' for z, t, lane, c, msg, g in codes)
            data = re.sub(rb'(<plate_info id="1"/>\n).*?(<mode )', b'\\g<1>' + lines.encode() + b'\\g<2>',
                          data, flags=re.S)
        elif n == "Metadata/project_settings.config":
            d = json.loads(data)
            project_filaments(d, order, swapped_lanes)
            d["top_surface_speed"] = ["120"]
            d["outer_wall_speed"] = ["120"]
            d["sparse_infill_density"] = "100%"
            d["ironing_type"] = "no ironing"
            if bed:
                d["curr_bed_type"] = bed
            if layer_height:
                d["layer_height"] = f"{layer_height:g}"
            thinnest = min((h for _, _, h in ranges), default=0.08)
            if thinnest < 0.08:
                d["min_layer_height"] = [f"{thinnest:g}"]   # the A1 0.4 profile stops at 0.08
            d.update(extra or {})
            data = json.dumps(d, indent=4).encode()
        elif n.endswith(".png"):           # plate images and the project thumbnails (Auxiliaries/)
            data = _thumb(preview, Image.open(io.BytesIO(data)).width)
        item.compress_type = zipfile.ZIP_DEFLATED     # the template may store small files uncompressed
        zout.writestr(item, data)
    if ranges:
        # Bambu Studio's height range modifier (bbs_3mf.cpp, layer_config_ranges.xml)
        zout.writestr("Metadata/layer_config_ranges.xml",
                      '<?xml version="1.0" encoding="utf-8"?>\n<objects>\n <object id="1">\n'
                      + "".join(f'  <range min_z="{lo:.2f}" max_z="{hi:.2f}">\n'
                                f'   <option opt_key="layer_height">{h:g}</option>\n  </range>\n'
                                for lo, hi, h in sorted(ranges))
                      + ' </object>\n</objects>\n', zipfile.ZIP_DEFLATED)
    zout.close()
