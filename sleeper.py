from __future__ import annotations

import httpx

BASE = "https://api.sleeper.app/v1"


async def get_league(league_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}")
        r.raise_for_status()
        return r.json()
async def get_standings(league_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}/rosters")
        r.raise_for_status()
        return r.json()
async def get_standings(league_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}/rosters")
        r.raise_for_status()
        return r.json()
async def get_users(league_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}/users")
        r.raise_for_status()
        return r.json()

async def get_matchups(league_id: str, week: int):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}/matchups/{week}")
        r.raise_for_status()
        return r.json()

async def get_nfl_state():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/state/nfl")
        r.raise_for_status()
        return r.json()
async def get_transactions(league_id: str, week: int):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE}/league/{league_id}/transactions/{week}")
        r.raise_for_status()
        return r.json()
import json
import os
from datetime import datetime, timedelta

PLAYERS_URL = f"{BASE}/players/nfl"
_PLAYERS_CACHE_PATH = "players.cache.json"
_PLAYERS_CACHE_TTL_HOURS = 24
_players = None  # in-memory cache

def _cache_fresh(path: str, ttl_hours: int) -> bool:
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        return datetime.now() - mtime < timedelta(hours=ttl_hours)
    except Exception:
        return False

async def get_players():
    """Return a dict of {player_id: player_dict}. Cached to disk for 24h."""
    global _players
    if _players is not None:
        return _players

    # Try disk cache first
    if os.path.exists(_PLAYERS_CACHE_PATH) and _cache_fresh(_PLAYERS_CACHE_PATH, _PLAYERS_CACHE_TTL_HOURS):
        try:
            with open(_PLAYERS_CACHE_PATH, "r", encoding="utf-8") as f:
                _players = json.load(f)
                return _players
        except Exception:
            pass

    # Fetch from Sleeper
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(PLAYERS_URL)
        r.raise_for_status()
        data = r.json()

    # Save to disk (best-effort)
    try:
        with open(_PLAYERS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

    _players = data
    return _players

def player_label(p: dict | None) -> str:
    """Return a short, human-friendly label for a player dict."""
    if not p:
        return "Unknown Player"
    # Sleeper fields commonly present: full_name, first_name, last_name, position, team
    name = p.get("full_name") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")])) or p.get("last_name") or "Unknown"
    pos = p.get("position") or ""
    team = p.get("team") or ""
    suffix = " ".join(filter(None, [pos, team])).strip()
    return f"{name} ({suffix})" if suffix else name
