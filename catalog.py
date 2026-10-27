"""Character catalog: scans Portraits/<Campaign>/<Faction>/, builds Discord-ready avatar PNGs, and
keeps characters.json (default names, crop overrides) in sync.

Run directly to sync from the command line:
    python catalog.py            # process new/changed portraits
    python catalog.py --force    # rebuild every avatar (e.g. after editing a crop)
"""

import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
PORTRAITS_DIR = ROOT / "Portraits"
AVATARS_DIR = ROOT / "avatars"
CHARACTERS_FILE = ROOT / "characters.json"

# Portraits used to be Portraits/<Faction>/; those folders now live in this campaign.
DEFAULT_CAMPAIGN = "Fortune's Weave"

AVATAR_SIZE = 512
IMAGE_EXTS = {".webp", ".png", ".jpg", ".jpeg", ".gif"}

# Filename noise to strip when guessing a display name.
_NAME_NOISE = [
    re.compile(r"^FEFW_Nintendo_Today_", re.I),
    re.compile(r"^Artwork_", re.I),
    re.compile(r"^(Medium|Small|Large)_portrait_", re.I),
    re.compile(r"_profile$", re.I),
    re.compile(r"_FE\d+$", re.I),
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


def backdrop(color: str, size: int = AVATAR_SIZE) -> Image.Image:
    """A soft radial glow in `color`: a little lighter in the middle, darker at the edges."""
    base = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    small = 64
    img = Image.new("RGB", (small, small))
    c = (small - 1) / 2
    for y in range(small):
        for x in range(small):
            t = min(1.0, (((x - c) ** 2 + (y - c) ** 2) ** 0.5) / (c * 1.42))
            k = 1.35 - 0.6 * t  # 1.35x at the centre, 0.75x at the corners
            img.putpixel((x, y), tuple(min(255, round(v * k)) for v in base))
    return img.resize((size, size), Image.BICUBIC).convert("RGBA")


def render_avatar(source: Path, dest: Path, crop: list, background: str | None = None) -> None:
    """crop = [left, top, size]; left/size are fractions of width, top of height.

    `background` (a hex colour) fills any transparent areas with a soft backdrop.
    """
    with Image.open(source) as im:
        im = im.convert("RGBA")
        w, h = im.size
        left, top, size = crop
        side = size * w
        box = (round(left * w), round(top * h), round(left * w + side), round(top * h + side))
        im = im.crop(box).resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        if background:
            im = Image.alpha_composite(backdrop(background), im)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "PNG", optimize=True)


def zoom_avatar(character: dict) -> str:
    """Path (under avatars/) of the close-up variant, for characters with a "zoom" crop."""
    return character["avatar"].removesuffix(".png") + "-zoom.png"


def campaigns() -> list:
    """Campaign folders in Portraits/, including empty ones just created."""
    if not PORTRAITS_DIR.exists():
        return []
    return sorted(d.name for d in PORTRAITS_DIR.iterdir() if d.is_dir())


def migrate_layout(characters: dict) -> bool:
    """Move old Portraits/<Faction>/ folders into Portraits/<DEFAULT_CAMPAIGN>/ and point
    their characters at the new paths, so names, crops and avatars carry over. Safe to re-run."""
    changed = False
    target = PORTRAITS_DIR / DEFAULT_CAMPAIGN
    for c in characters.values():
        parts = c["source"].split("/")
        if len(parts) == 3:  # Portraits/<Faction>/<file>
            old_dir = PORTRAITS_DIR / parts[1]
            new_dir = target / parts[1]
            if old_dir.is_dir():
                new_dir.mkdir(parents=True, exist_ok=True)
                for f in list(old_dir.iterdir()):
                    if not (new_dir / f.name).exists():
                        shutil.move(str(f), str(new_dir / f.name))
                if not any(old_dir.iterdir()):
                    old_dir.rmdir()
            c["source"] = f"Portraits/{DEFAULT_CAMPAIGN}/{parts[1]}/{parts[2]}"
            changed = True
        if "campaign" not in c:
            c["campaign"] = c["source"].split("/")[1]
            changed = True
    return changed


def rename_campaign(characters: dict, old: str, new: str) -> None:
    """Rename a campaign folder and repoint its characters (avatar files and links don't change)."""
    src, dst = PORTRAITS_DIR / old, PORTRAITS_DIR / new
    if dst.exists():
        raise FileExistsError(f'There is already a "{new}" folder in Portraits.')
    src.rename(dst)
    for c in characters.values():
        if c.get("campaign") == old:
            c["campaign"] = new
            c["source"] = f"Portraits/{new}/" + c["source"].split("/", 2)[2]
    save_characters(characters)


def sync(force: bool = False, progress=None) -> dict:
    """Bring characters.json and avatars/ in line with Portraits/.

    Existing names and crops are preserved. `progress(done, total, label)` is
    called while avatars are rendered. Returns the updated catalog.
    """
    characters = load_characters()
    migrate_layout(characters)
    by_source = {c["source"]: cid for cid, c in characters.items()}
    seen = set()

    sources = sorted(
        p for p in PORTRAITS_DIR.glob("*/*/*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    for path in sources:
        source = path.relative_to(ROOT).as_posix()
        cid = by_source.get(source)
        if cid is None:
            faction, campaign = path.parent.name, path.parent.parent.name
            base = f"{slugify(faction)}/{slugify(guess_name(path.name))}"
            if campaign != DEFAULT_CAMPAIGN:  # keep campaigns' avatar paths apart
                base = f"{slugify(campaign)}/{base}"
            cid, n = base, 2
            while cid in characters:
                cid, n = f"{base}-{n}", n + 1
            with Image.open(path) as im:
                crop = default_crop(*im.size)
            characters[cid] = {
                "name": guess_name(path.name),
                "faction": faction,
                "campaign": campaign,
                "source": source,
                "avatar": f"{cid}.png",
                "crop": crop,
            }
        seen.add(cid)

    for cid in list(characters):
        if cid not in seen:
            del characters[cid]

    todo = []  # (character, avatar path, crop)
    for cid, c in characters.items():
        src = ROOT / c["source"]
        variants = [(c["avatar"], c["crop"])]
        if c.get("zoom"):
            variants.append((zoom_avatar(c), c["zoom"]))
        for avatar, crop in variants:
            dest = AVATARS_DIR / avatar
            if force or not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
                todo.append((c, avatar, crop))

    for i, (c, avatar, crop) in enumerate(todo):
        if progress:
            progress(i, len(todo), c["name"])
        render_avatar(ROOT / c["source"], AVATARS_DIR / avatar, crop, c.get("background"))
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
