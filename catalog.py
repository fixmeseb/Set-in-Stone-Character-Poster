"""Character catalog: scans Portraits/, builds Discord-ready avatar PNGs, and
keeps characters.json (default names, crop overrides) in sync.

Run directly to sync from the command line:
    python catalog.py            # process new/changed portraits
    python catalog.py --force    # rebuild every avatar (e.g. after editing a crop)
"""

import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
PORTRAITS_DIR = ROOT / "Portraits"
AVATARS_DIR = ROOT / "avatars"
CHARACTERS_FILE = ROOT / "characters.json"

AVATAR_SIZE = 512
IMAGE_EXTS = {".webp", ".png", ".jpg", ".jpeg", ".gif"}

# Filename noise to strip when guessing a display name.
_NAME_NOISE = [
    re.compile(r"^FEFW_Nintendo_Today_", re.I),
    re.compile(r"_profile$", re.I),
    re.compile(r"FE\d+Portrait$", re.I),
    re.compile(r"[ _]?Portrait$", re.I),
]


def strip_extensions(filename: str) -> str:
    """'Foo.webp.png' -> 'Foo'."""
    stem = filename
    while Path(stem).suffix.lower() in IMAGE_EXTS:
        stem = Path(stem).stem
    return stem


def guess_name(filename: str) -> str:
    name = strip_extensions(filename)
    for pattern in _NAME_NOISE:
        name = pattern.sub("", name)
    name = name.replace("_", " ").strip()
    if " " not in name:
        # Split CamelCase: 'BahrVahn' -> 'Bahr Vahn'
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return name or strip_extensions(filename)


def slugify(text: str) -> str:
    text = text.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def load_characters() -> dict:
    if CHARACTERS_FILE.exists():
        with open(CHARACTERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_characters(characters: dict) -> None:
    ordered = dict(sorted(characters.items(), key=lambda kv: (kv[1]["faction"], kv[1]["name"].lower())))
    with open(CHARACTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")


def default_crop(width: int, height: int) -> list:
    """Square crop as [left, top, size] fractions of the image.

    Tall (full-body) art is cropped from the top so the head stays in frame;
    wide art is cropped from the centre.
    """
    if height > width:
        return [0.0, 0.0, 1.0]
    if width > height:
        side = height / width
        return [round((1 - side) / 2, 4), 0.0, round(side, 4)]
    return [0.0, 0.0, 1.0]


def render_avatar(source: Path, dest: Path, crop: list) -> None:
    """crop = [left, top, size]; left/size are fractions of width, top of height."""
    with Image.open(source) as im:
        im = im.convert("RGBA")
        w, h = im.size
        left, top, size = crop
        side = size * w
        box = (round(left * w), round(top * h), round(left * w + side), round(top * h + side))
        im = im.crop(box).resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "PNG", optimize=True)


def sync(force: bool = False, progress=None) -> dict:
    """Bring characters.json and avatars/ in line with Portraits/.

    Existing names and crops are preserved. `progress(done, total, label)` is
    called while avatars are rendered. Returns the updated catalog.
    """
    characters = load_characters()
    by_source = {c["source"]: cid for cid, c in characters.items()}
    seen = set()

    sources = sorted(
        p for p in PORTRAITS_DIR.glob("*/*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    for path in sources:
        source = path.relative_to(ROOT).as_posix()
        cid = by_source.get(source)
        if cid is None:
            faction = path.parent.name
            base = f"{slugify(faction)}/{slugify(guess_name(path.name))}"
            cid, n = base, 2
            while cid in characters:
                cid, n = f"{base}-{n}", n + 1
            with Image.open(path) as im:
                crop = default_crop(*im.size)
            characters[cid] = {
                "name": guess_name(path.name),
                "faction": faction,
                "source": source,
                "avatar": f"{cid}.png",
                "crop": crop,
            }
        seen.add(cid)

    for cid in list(characters):
        if cid not in seen:
            del characters[cid]

    todo = []
    for cid, c in characters.items():
        src, dest = ROOT / c["source"], AVATARS_DIR / c["avatar"]
        if force or not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
            todo.append(c)

    for i, c in enumerate(todo):
        if progress:
            progress(i, len(todo), c["name"])
        render_avatar(ROOT / c["source"], AVATARS_DIR / c["avatar"], c["crop"])
    if progress:
        progress(len(todo), len(todo), "")

    save_characters(characters)
    return characters


if __name__ == "__main__":
    def _print_progress(done, total, label):
        if label:
            print(f"[{done + 1}/{total}] {label}")

    result = sync(force="--force" in sys.argv, progress=_print_progress)
    print(f"{len(result)} characters in {CHARACTERS_FILE.name}")
