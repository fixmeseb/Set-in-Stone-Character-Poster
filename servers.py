"""Discord servers and their channels, stored in channel_list.json.

    {"servers": {"<server name>": {"guild_id": "<Discord server id or null>",
                                   "channels": {"<channel name>": "<webhook URL>"}}}}

Older files were a flat {"<channel name>": "<webhook URL>"} map. `is_legacy` spots those and
`migrate` groups their channels by the Discord server each webhook posts to.
"""

import json
import re
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_legacy(data: dict) -> bool:
    return bool(data) and "servers" not in data and all(isinstance(v, str) for v in data.values())


def migrate(flat: dict, guild_of, name_for) -> dict:
    """Group a legacy {channel: url} map into servers.

    `guild_of(url)` returns the webhook's Discord server id (or None if it can't be checked);
    `name_for(guild_id, channel_names, taken_names)` picks a name for each new server.
    """
    groups = {}
    for channel, url in flat.items():
        groups.setdefault(guild_of(url), {})[channel] = url
    servers = {}
    for guild_id, channels in groups.items():
        name = name_for(guild_id, list(channels), set(servers))
        servers[name] = {"guild_id": guild_id, "channels": channels}
    return servers


def save(path: Path, servers: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"servers": servers}, f, indent=4, ensure_ascii=False)
        f.write("\n")


def history_key(server: str, channel: str) -> str:
    """Key for history.json, so same-named channels in different servers stay apart."""
    return f"{server} › {channel}"


def initials(name: str) -> str:
    """Badge text: 'Set in Stone' -> 'SiS', "Friends' Hangout" -> 'FH', 'Campaign' -> 'Ca'."""
    words = [w for w in re.split(r"[\s_\-]+", re.sub(r"[^\w\s\-]", "", name)) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][0].upper() + words[0][1:2].lower()
    return "".join(w[0] for w in words[:3])
