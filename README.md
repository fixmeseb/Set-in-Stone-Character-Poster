# Set in Stone Character Board

A PyQt6 app for posting to Discord as a character via webhooks.

## Run

```
pip install -r requirements.txt
python app.py
```

## Files

| File | Purpose
|---|---|---|
| `Portraits/<Faction>/*` | Original art. Folder name = faction.
| `avatars/` | 512×512 PNG avatars generated from Portraits. Must be public for Discord.
| `characters.json` | Default display names and avatar crops, generated/updated by `catalog.py`.
| `settings.json` | `avatar_base_url` (set via File → Settings).

## Adding characters

Drop the image into `Portraits/<Faction>/`, then **File → Rescan portraits** (or restart).
The name is guessed from the filename; fix it in the app with **Save as default**.
Push `avatars/` to GitHub afterwards so the new avatar is reachable.

## Adjusting an avatar crop

Each character in `characters.json` has `"crop": [left, top, size]`:
`left` and `size` are fractions of the image width, `top` is a fraction of its height.
Edit it, then **File → Rebuild all avatars** (or `python catalog.py --force`).
