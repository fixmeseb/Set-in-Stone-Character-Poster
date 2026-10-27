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
| `Portraits/<Faction>/*` | Original art. Folder name = faction. | No (only avatars are needed) |
| `avatars/` | 512×512 PNG avatars generated from Portraits. Must be public for Discord. | **Yes** |
| `characters.json` | Default display names, favorites and avatar crops, generated/updated by `catalog.py`. | Yes |
| `channel_list.json` | Channel name → webhook URL. **Secret.** | **No** |
| `settings.json` | `avatar_base_url` (set via File → Settings). | Yes |
| `history.json` | Last message sent to each channel, shown faded above the preview. | No |
| `fonts/` | Cinzel and EB Garamond (SIL Open Font License), used by the Grimoire theme. | Yes |
| `app_icon.ico` | Window/taskbar icon, made from the Promised One's Army banner. | Yes |

## Using it

- **Pick a character** from the roster; filter by faction on the left, search with Ctrl+F, sort by faction or name.
- **Favorite** a character by hovering its portrait and clicking the star (or focus it and press F); the
  Favorites entry at the top of the faction list shows only them.
- **Compose** at the bottom right: edit the "As" name for this post (Reset / Save as default), pick a channel
  (right-click a channel to remove it, + Channel to add one), write the message, attach images with + or by
  dropping them on the window. The preview above shows exactly what will post; click ✕ on an image to drop it.
- **Send** with Seal & Send or Ctrl+Enter.

## Adding characters

Drop the image into `Portraits/<Faction>/`, then **File → Rescan portraits** (or restart).
The name is guessed from the filename; fix it in the app with **Save as default**.
Push `avatars/` to GitHub afterwards so the new avatar is reachable.

## Adjusting an avatar crop

Easiest: select the character and click **Edit framing…** (under the message box, or in the File menu).
Switch between the Normal and Zoomed frames, drag the frame / scroll to zoom, and **Save as default** —
this updates `characters.json` and re-renders the avatar PNG. Push `avatars/` afterwards.

By hand: each character in `characters.json` has `"crop": [left, top, size]`:
`left` and `size` are fractions of the image width, `top` is a fraction of its height.
Edit it, then **File → Rebuild all avatars** (or `python catalog.py --force`).

Optional extras per character:
- `"zoom": [left, top, size]` — a second, close-up crop saved as `<name>-zoom.png`. The **Zoomed avatar**
  checkbox under the message box posts with it (greyed out for characters without one).
- `"background": "#rrggbb"` — fills transparent areas with a soft backdrop in that colour (used for the Gods of Dagda).
