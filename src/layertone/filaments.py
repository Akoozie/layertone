"""Filament library: colour, transmission distance (TD) and AMS slot."""
from dataclasses import dataclass
import json
from pathlib import Path

LIBRARY = Path(__file__).with_name("filaments.json")


@dataclass(frozen=True)
class Filament:
    key: str
    name: str
    hex: str
    td: float           # mm, HueForge-style transmission distance
    slot: int           # AMS lite slot in the printer template (1-4)

    @property
    def rgb(self):
        h = self.hex.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def load_library(path=LIBRARY):
    data = json.loads(Path(path).read_text())
    return {k: Filament(key=k, **v) for k, v in data.items()}


def save_library(entries, path=LIBRARY):
    """Check and write the whole library. entries: key -> {name, hex, td, slot}."""
    clean = {}
    for k, v in entries.items():
        k = "".join(c for c in k.lower().replace(" ", "_") if c.isalnum() or c == "_")
        h = str(v["hex"]).strip()
        if not k or len(h) != 7 or h[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in h[1:]):
            raise ValueError(f"bad filament {k!r}: colour must look like #RRGGBB")
        td, slot = float(v["td"]), int(v["slot"])
        if not (0.05 <= td <= 50) or not (1 <= slot <= 4):
            raise ValueError(f"{v['name']}: TD must be 0.05-50 mm and slot 1-4")
        clean[k] = {"name": str(v["name"]).strip() or k, "hex": h.upper(), "td": td, "slot": slot}
    if not clean:
        raise ValueError("keep at least one filament")
    Path(path).write_text("{\n" + ",\n".join(f'  {json.dumps(k)}: {json.dumps(v)}' for k, v in clean.items()) + "\n}\n")
    return load_library(path)


def pick(keys, library=None):
    lib = library or load_library()
    missing = [k for k in keys if k not in lib]
    if missing:
        raise SystemExit(f"unknown filament(s) {missing}; known: {sorted(lib)}")
    return [lib[k] for k in keys]
