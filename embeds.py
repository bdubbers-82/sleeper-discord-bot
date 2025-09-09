from __future__ import annotations
import discord
from datetime import datetime, timezone

PRIMARY = 0x4F46E5  # indigo
SUCCESS = 0x16A34A  # green
WARN    = 0xEAB308  # amber
ERROR   = 0xDC2626  # red
INFO    = 0x0EA5E9  # sky

def card(title: str, desc: str | None = None, color: int = PRIMARY) -> discord.Embed:
    e = discord.Embed(title=title, description=desc or "", color=color)
    e.timestamp = datetime.now(timezone.utc)
    return e

def add_kv(e: discord.Embed, name: str, value: str, inline: bool = False) -> None:
    e.add_field(name=name, value=value, inline=inline)
