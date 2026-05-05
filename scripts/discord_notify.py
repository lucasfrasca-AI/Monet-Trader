"""Discord webhook poster.

Embed colour coding (decimal RGB, sourced from config.yaml):
  green   = fill          (new entry filled / partial fill)
  red     = stop_loss     (stop or hard loss exit)
  yellow  = summary       (daily / weekly P&L summary)
  orange  = warning       (risk caps approaching, throttling)
  blue    = info          (general status, dry-run output)
  dark-red = critical     (kill-switch tripped, API failure)

All Discord traffic in Monet-Trader goes through this module.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DEFAULT_TIMEOUT_S = 10
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def _colours() -> dict[str, int]:
    with CONFIG_PATH.open("r") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("discord_colours", {})


COLOURS = _colours()


class DiscordError(RuntimeError):
    """Webhook post returned a non-2xx status."""


def _post_embed(title: str, description: str, colour: int, fields: list[dict[str, Any]] | None = None) -> bool:
    """Post an embed. Returns True on success, False on failure (non-blocking).

    Per CLAUDE.md: Discord webhook failures must NOT halt a routine. Callers
    should treat False as 'log to research_log and continue'.
    """
    if not WEBHOOK_URL:
        print("[discord_notify] DISCORD_WEBHOOK_URL missing; skipping post")
        return False

    embed: dict[str, Any] = {
        "title": title[:256],
        "description": description[:4000],
        "color": colour,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields[:25]

    try:
        resp = requests.post(
            WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=DEFAULT_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        print(f"[discord_notify] webhook request failed: {exc}")
        return False

    if resp.status_code not in (200, 204):
        print(f"[discord_notify] webhook returned {resp.status_code}: {resp.text[:200]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Public API — typed helpers per message category
# ---------------------------------------------------------------------------

def info(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(title, description, COLOURS.get("info", 3447003), fields)


def fill(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(title, description, COLOURS.get("fill", 3066993), fields)


def stop_loss(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(title, description, COLOURS.get("stop_loss", 15158332), fields)


def summary(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(title, description, COLOURS.get("summary", 15844367), fields)


def warning(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(title, description, COLOURS.get("warning", 15105570), fields)


def critical(title: str, description: str, fields: list[dict[str, Any]] | None = None) -> bool:
    return _post_embed(
        title,
        description,
        COLOURS.get("critical", 10038562),
        fields,
    )


def plain(content: str) -> bool:
    """Send a plain (non-embed) message. Use sparingly — embeds are preferred."""
    if not WEBHOOK_URL:
        return False
    try:
        resp = requests.post(WEBHOOK_URL, json={"content": content[:1900]}, timeout=DEFAULT_TIMEOUT_S)
    except requests.RequestException:
        return False
    return resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ok = info(
        "module 2 verified ✅",
        "discord_notify.py self-test reached the channel.",
        fields=[
            {"name": "module", "value": "scripts/discord_notify.py", "inline": True},
            {"name": "colours_loaded", "value": str(len(COLOURS)), "inline": True},
        ],
    )
    print(f"info post -> {ok}")
