"""Character bot: when the chosen user writes "{Sothis}: Hello", it reposts "Hello" as Sothis through a webhook,
using the same names and avatars as the Character Board, then deletes the original.

Setup (see README, "Character bot"): copy bot_config.example.json to bot_config.json, fill in the bot token and
server id, and run  python bot.py
"""

import json
import logging
import os
import re
from pathlib import Path

import discord

import catalog
import servers

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "bot_config.json"
CHARACTERS_FILE = ROOT / "characters.json"
SETTINGS_FILE = ROOT / "settings.json"
CHANNELS_FILE = ROOT / "channel_list.json"
WEBHOOK_NAME = "Set in Stone Characters"

# "{Name}: text" at the very start of the message; the text may run over several lines (or be empty, with images).
TRIGGER = re.compile(r"\A\s*\{([^{}\n]+)\}:\s*(.*)\Z", re.DOTALL)

log = logging.getLogger("character-bot")


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def load_config() -> dict:
    config = load_json(CONFIG_FILE, {})
    config["token"] = os.environ.get("DISCORD_BOT_TOKEN") or config.get("token", "")
    missing = [k for k in ("token", "guild_id", "user_id") if not str(config.get(k, "")).strip()]
    if missing:
        raise SystemExit(f"bot_config.json is missing {', '.join(missing)} "
                         "(copy bot_config.example.json to bot_config.json and fill it in).")
    config["guild_id"] = int(config["guild_id"])
    config["user_id"] = int(config["user_id"])
    config.setdefault("campaign", "")
    config.setdefault("zoom", False)
    config.setdefault("delete_original", True)
    return config


def parse_trigger(content: str):
    """("Sothis", "Hello") for "{Sothis}: Hello", or None when the message isn't meant for a character."""
    m = TRIGGER.match(content)
    return (m.group(1).strip(), m.group(2)) if m and m.group(1).strip() else None


def find_character(characters: dict, name: str, campaign: str = ""):
    """The (id, character) that "{name}" means, or None.

    Matches the character's default name, or the last part of its id, so same-named characters can still be told
    apart ("Peridot2", "Yu Phas 2"). Ignores case and punctuation. Characters from the configured campaign come first,
    then exact name matches over id matches.
    """
    want = catalog.slugify(name)
    if not want:
        return None
    matches = [(cid, c) for cid, c in characters.items()
               if want in (catalog.slugify(c["name"]), cid.rsplit("/", 1)[-1])]

    def rank(item):
        cid, c = item
        other_campaign = bool(campaign) and c.get("campaign", catalog.DEFAULT_CAMPAIGN) != campaign
        return other_campaign, catalog.slugify(c["name"]) != want

    return min(matches, key=rank, default=None)  # min keeps the first of equals, so file order breaks ties


def avatar_url(base: str, character: dict, zoom: bool = False) -> str | None:
    """The character's avatar URL, built the way the app builds it."""
    if not base.strip():
        return None
    path = catalog.zoom_avatar(character) if zoom and character.get("zoom") else character["avatar"]
    return f'{base.strip().rstrip("/")}/{path}'


class Roster:
    """characters.json, reloaded whenever the app changes it, so new or renamed characters work without a restart."""

    def __init__(self, path: Path = CHARACTERS_FILE):
        self.path = path
        self.mtime = None
        self.characters = {}

    def get(self) -> dict:
        mtime = self.path.stat().st_mtime if self.path.exists() else None
        if mtime != self.mtime:
            self.characters = load_json(self.path, {})
            self.mtime = mtime
        return self.characters


class CharacterBot(discord.Client):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True  # also switch on "Message Content Intent" in the Developer Portal
        super().__init__(intents=intents)
        self.config = config
        self.roster = Roster()
        self.webhooks = {}  # channel id -> discord.Webhook
        self.warned_delete = False

    async def setup_hook(self):
        await self.load_app_webhooks()

    async def load_app_webhooks(self):
        """Post through the app's own webhook where a channel has one, so the app's Edit Mode can edit those posts
        too (via + Older message…). Other channels get a webhook the bot makes itself."""
        data = servers.load(CHANNELS_FILE).get("servers", {})
        for server in data.values():
            if str(server.get("guild_id")) != str(self.config["guild_id"]):
                continue
            for channel, url in server.get("channels", {}).items():
                try:
                    hook = discord.Webhook.from_url(url, client=self)
                    info = await hook.fetch()
                    self.webhooks[info.channel_id] = hook
                except (discord.HTTPException, ValueError) as e:
                    log.warning("Skipping the app's webhook for #%s: %s", channel, e)
        log.info("Using the app's webhooks in %d channel(s)", len(self.webhooks))

    async def on_ready(self):
        guild = self.get_guild(self.config["guild_id"])
        if guild is None:
            log.error("The bot isn't in server %s; invite it first.", self.config["guild_id"])
        else:
            log.info("Logged in as %s, watching %s for messages from user %s",
                     self.user, guild.name, self.config["user_id"])

    async def webhook_for(self, channel) -> discord.Webhook:
        if channel.id not in self.webhooks:
            hooks = await channel.webhooks()  # needs Manage Webhooks
            hook = next((h for h in hooks if h.user == self.user and h.token), None)
            self.webhooks[channel.id] = hook or await channel.create_webhook(name=WEBHOOK_NAME)
        return self.webhooks[channel.id]

    async def on_message(self, message: discord.Message):
        if (message.guild is None or message.guild.id != self.config["guild_id"]
                or message.author.id != self.config["user_id"] or message.webhook_id):
            return
        parsed = parse_trigger(message.content)
        if not parsed:
            return
        name, text = parsed
        found = find_character(self.roster.get(), name, self.config["campaign"])
        if not found:
            log.info("No character called %r", name)
            return await self.react(message, "❓")
        if not text.strip() and not message.attachments:
            return
        cid, character = found

        # A message in a thread (or forum post) goes through its parent channel's webhook.
        thread = message.channel if isinstance(message.channel, discord.Thread) else None
        channel = thread.parent if thread else message.channel
        try:
            hook = await self.webhook_for(channel)
            files = [await a.to_file(spoiler=a.is_spoiler()) for a in message.attachments]
            await hook.send(
                content=text, username=character["name"][:80],
                avatar_url=avatar_url(load_json(SETTINGS_FILE, {}).get("avatar_base_url", ""), character,
                                      self.config["zoom"]),
                files=files, thread=thread or discord.utils.MISSING,
                allowed_mentions=discord.AllowedMentions(everyone=False), wait=True)
        except discord.Forbidden:
            log.error("Missing permission to use webhooks in #%s (the bot needs Manage Webhooks)", channel)
            return await self.react(message, "⚠️")
        except discord.HTTPException as e:
            self.webhooks.pop(channel.id, None)  # it may have been deleted; make a fresh one next time
            log.error("Couldn't post as %s in #%s: %s", character["name"], channel, e)
            return await self.react(message, "⚠️")
        log.info("Posted as %s (%s) in #%s", character["name"], cid, message.channel)

        if self.config["delete_original"]:
            try:
                await message.delete()
            except discord.Forbidden:
                if not self.warned_delete:
                    log.warning("Can't delete the original messages (the bot needs Manage Messages)")
                    self.warned_delete = True
            except discord.NotFound:
                pass

    @staticmethod
    async def react(message, emoji):
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass


def main():
    config = load_config()
    CharacterBot(config).run(config["token"])


if __name__ == "__main__":
    main()
