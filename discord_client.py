"""Minimal Discord webhook client."""

import json
import mimetypes
import re
import time
from pathlib import Path

import requests

WEBHOOK_RE = re.compile(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+/?$")

MAX_CONTENT = 2000
MAX_USERNAME = 80
MAX_FILES = 10
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # default per-message limit for webhooks
_FORBIDDEN_IN_USERNAME = ("discord", "clyde")


class WebhookError(Exception):
    pass


def validate_message(content: str, username: str, files: list) -> list:
    """Return a list of problems that would make Discord reject the message."""
    problems = []
    if not content.strip() and not files:
        problems.append("Message is empty.")
    if len(content) > MAX_CONTENT:
        problems.append(f"Message is {len(content)} characters (max {MAX_CONTENT}).")
    if not username.strip():
        problems.append("Display name is empty.")
    elif len(username) > MAX_USERNAME:
        problems.append(f"Display name is {len(username)} characters (max {MAX_USERNAME}).")
    lowered = username.lower()
    for word in _FORBIDDEN_IN_USERNAME:
        if word in lowered:
            problems.append(f'Discord doesn\'t allow "{word}" in webhook names.')
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} images attached (max {MAX_FILES}).")
    total = sum(Path(f).stat().st_size for f in files if Path(f).exists())
    if total > MAX_UPLOAD_BYTES:
        problems.append(f"Attachments total {total / 1_048_576:.1f} MB (max {MAX_UPLOAD_BYTES // 1_048_576} MB).")
    return problems


def fetch_webhook_info(url: str) -> dict:
    """GET the webhook to confirm it exists. Returns Discord's webhook object."""
    if not WEBHOOK_RE.match(url):
        raise WebhookError("That doesn't look like a Discord webhook URL.")
    try:
        r = requests.get(url, timeout=10)
    except requests.RequestException as e:
        raise WebhookError(f"Couldn't reach Discord: {e}") from e
    if r.status_code != 200:
        raise WebhookError(f"Discord rejected the webhook ({r.status_code}): {_error_text(r)}")
    return r.json()


def send_message(url: str, content: str, username: str, avatar_url: str | None, files: list, retries: int = 3) -> dict:
    """Post a message; returns Discord's message object (its "id" is what edit/delete need)."""
    payload = {"content": content, "username": username}
    if avatar_url:
        payload["avatar_url"] = avatar_url
    return _request("POST", url, payload, files, params={"wait": "true"}, retries=retries)


def message_url(url: str, message_id: str) -> str:
    return f"{url.rstrip('/')}/messages/{message_id}"


def fetch_message(url: str, message_id: str) -> dict:
    """A message this webhook posted. Discord answers 404 for anything else (or a deleted message)."""
    return _request("GET", message_url(url, message_id))


def edit_message(url: str, message_id: str, content: str, files: list, keep_attachments: list) -> dict:
    """Change a webhook message's text and images. The name and avatar it was posted with can't change.

    keep_attachments lists the ids of images already on the message that should stay; the rest are removed.
    """
    attachments = [{"id": a} for a in keep_attachments]
    attachments += [{"id": i, "filename": Path(f).name} for i, f in enumerate(files)]
    return _request("PATCH", message_url(url, message_id), {"content": content, "attachments": attachments}, files)


def delete_message(url: str, message_id: str) -> None:
    _request("DELETE", message_url(url, message_id))


def message_id_from(text: str) -> str | None:
    """The message id in a pasted message link (the last number in it) or a bare id."""
    ids = re.findall(r"\d{15,22}", text)
    return ids[-1] if ids else None


def _request(method: str, url: str, payload: dict | None = None, files: list = (), params=None, retries: int = 3):
    for _ in range(retries + 1):
        handles = []
        try:
            if files:
                multipart = {}
                for i, f in enumerate(files):
                    path = Path(f)
                    fh = open(path, "rb")
                    handles.append(fh)
                    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    multipart[f"files[{i}]"] = (path.name, fh, mime)
                r = requests.request(method, url, params=params,
                                     data={"payload_json": json.dumps(payload)}, files=multipart, timeout=60)
            else:
                r = requests.request(method, url, params=params, json=payload, timeout=30)
        except requests.RequestException as e:
            raise WebhookError(f"Couldn't reach Discord: {e}") from e
        finally:
            for fh in handles:
                fh.close()

        if r.status_code == 429:
            try:
                wait = float(r.json().get("retry_after", 1))
            except ValueError:
                wait = 1.0
            time.sleep(min(wait, 30))
            continue
        if r.status_code == 204:
            return None
        if r.ok:
            return r.json()
        if r.status_code == 404 and "/messages/" in url:
            raise WebhookError("Discord can't find that message for this channel's webhook. It may have been "
                               "deleted, or it was posted by someone else or through a different webhook.")
        raise WebhookError(f"Discord returned {r.status_code}: {_error_text(r)}")

    raise WebhookError("Rate limited by Discord; try again in a moment.")


def _error_text(r: requests.Response) -> str:
    try:
        data = r.json()
        msg = data.get("message", "")
        errors = data.get("errors")
        return f"{msg} {json.dumps(errors)}" if errors else msg or r.text
    except ValueError:
        return r.text[:300]
