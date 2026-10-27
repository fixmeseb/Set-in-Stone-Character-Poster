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
| `Portraits/<Campaign>/<Faction>/*` | Original art. Folder names = campaign and faction. | No (only avatars are needed) |
| `avatars/` | 512×512 PNG avatars generated from Portraits. Must be public for Discord. | **Yes** |
| `characters.json` | Default display names, favorites and avatar crops, generated/updated by `catalog.py`. | Yes |
| `channel_list.json` | Servers → channel name → webhook URL. **Secret.** | **No** |
| `settings.json` | `avatar_base_url` (set via File → Settings). | Yes |
| `history.json` | Last message sent to each channel, shown faded above the preview. | No |
| `fonts/` | Cinzel and EB Garamond (SIL Open Font License), used by the Grimoire theme. | Yes |
| `app_icon.ico` | Window/taskbar icon, made from the Promised One's Army banner. | Yes |

## Using it

- **Pick a character** from the roster; filter by faction on the left, search with Ctrl+F, sort by faction or name.
- **Favorite** a character by hovering its portrait and clicking the star (or focus it and press F); the
  Favorites entry at the top of the faction list shows only them.
- **Pick a server** from the rail of badges at the left of the composer (+ adds a server; right-click a badge
  to rename or remove it). Each server remembers the channel you last used in it.
- **Compose** at the bottom right: edit the "As" name for this post (Reset, or **Save as Default** in the row
  under the message box), pick a channel (right-click a channel to remove it, + Channel to add one), write the
  message, attach images with + or by dropping them on the window. The preview above shows exactly what will post; click ✕ on an image to drop it.
- **Send** with Seal & Send or Enter. Ctrl+Enter (or Shift+Enter) starts a new line.

## Adding characters

Drop the image into `Portraits/<Campaign>/<Faction>/`, then **File → Rescan portraits** (or restart).
The name is guessed from the filename; fix it in the app with **Save as default**.
Push `avatars/` to GitHub afterwards so the new avatar is reachable.

## Adjusting an avatar crop

Easiest: select the character and click **Edit Framing** (under the message box, or in the File menu).
Switch between the Normal and Zoomed frames, drag the frame / scroll to zoom, and **Save as default** —
this updates `characters.json` and re-renders the avatar PNG. Push `avatars/` afterwards.

By hand: each character in `characters.json` has `"crop": [left, top, size]`:
`left` and `size` are fractions of the image width, `top` is a fraction of its height.
Edit it, then **File → Rebuild all avatars** (or `python catalog.py --force`).

Optional extras per character:
- `"zoom": [left, top, size]` — a second, close-up crop saved as `<name>-zoom.png`. The **Zoomed Avatar**
  button under the message box posts with it (greyed out for characters without one).
- `"background": "#rrggbb"` — fills transparent areas with a soft backdrop in that colour (used for the Gods of Dagda).

## Servers

Adding a channel checks its webhook with Discord, which reports the server it posts to, so the channel is
filed under the right server automatically; a webhook from a server you haven't added yet asks you to name it.
An older flat `channel_list.json` is converted on first launch (you're asked to name each server once).
Right-click a server badge to rename it, **Set server image…** (saved as a 128 px square in `server_icons/`,
which stays on this machine) or remove it.

## Campaigns

Each folder in `Portraits/` is a campaign with its own factions, characters, favorites and faction order.
The campaign card at the top of the faction menu switches between them (click), and right-clicking it
renames the campaign, reorders the list or opens its folder. **New campaign…** creates
`Portraits/<name>/`; add a folder per faction inside it, then **File → Rescan portraits**.
Faction order and in-app faction renames are saved per campaign in `factions.json`.

## Views

**View** (next to **File**) switches the layout; the app reopens in the last one you used.

- **Classic** (Ctrl+1): the faction menu, the roster of round portraits, and the profile, preview and composer on the right.
- **Tarot Spread** (Ctrl+2): the chosen character is drawn as a large card with the full portrait art, with their
  neighbours tilted either side. The faction's cards run along the bottom as a deck, beside the full-height faction menu. The **Message** panel
  between the faction menu and the cards holds the server, channel, name, preview and message, with **Image**, **Save Name**, **Zoom** and
  **Framing** above **Post**. Click a side card, scroll over the big card, or press Left/Right to deal the next one.
