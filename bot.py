import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sleeper import (
    get_league,
    get_standings,
    get_users,
    get_matchups,
    get_nfl_state,
    get_transactions,
    get_players,
    player_label,
)
from embeds import card, add_kv, PRIMARY, SUCCESS, WARN, ERROR, INFO
from config import load_config, save_config, BotConfig

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ENV_LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0") or 0)
COMMISSIONER_IDS = {int(x.strip()) for x in (os.getenv("COMMISSIONER_IDS") or "").split(",") if x.strip().isdigit()}

CFG: BotConfig = load_config()
TZ = ZoneInfo("America/New_York")

intents = discord.Intents.none()
intents.guilds = True

class SleeperDiscordBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.scheduler: AsyncIOScheduler | None = None

    async def setup_hook(self):
        # Sync commands
        if not self.synced:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Slash commands synced to guild {GUILD_ID}.")
            else:
                await self.tree.sync()
                logger.info("Slash commands synced globally.")
            self.synced = True

        # Scheduler
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler(timezone=TZ)
            self.scheduler.start()
            logger.info("Scheduler started.")
            _register_preview_job(self.scheduler)
            _register_results_job(self.scheduler)

bot = SleeperDiscordBot()

def is_commissioner(user_id: int) -> bool:
    return user_id in COMMISSIONER_IDS

def commissioner_check(interaction: discord.Interaction) -> bool:
    if not is_commissioner(interaction.user.id):
        raise app_commands.CheckFailure("Commissioner-only command.")
    return True

def league_id_effective() -> str:
    return (CFG.league_id or ENV_LEAGUE_ID) or ""

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Config: {CFG}")
    logger.info("------")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    from discord.app_commands import CheckFailure
    logger.exception("Slash command error: %s", error)
    msg = "Something went wrong. Please try again."
    color = ERROR
    if isinstance(error, CheckFailure):
        msg = "Permission denied — commissioner only."
    try:
        await interaction.response.send_message(embed=card("Error", msg, color), ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(embed=card("Error", msg, color), ephemeral=True)

# ---------- Helpers ----------

def _name_map(users, rosters):
    uid_to_name = {u.get("user_id"): (u.get("display_name") or u.get("username") or "Unknown")
                   for u in users}
    rid_to_uid = {r.get("roster_id"): r.get("owner_id") for r in rosters}
    return {rid: uid_to_name.get(uid, f"Roster {rid}") for rid, uid in rid_to_uid.items()}

async def build_week_preview_embed(lid: str, week: int) -> discord.Embed:
    users = await get_users(lid)
    rosters = await get_standings(lid)
    roster_name = _name_map(users, rosters)
    m = await get_matchups(lid, week)
    e = card(f"Week {week} Preview", color=PRIMARY)
    if not m:
        add_kv(e, "No data", f"No matchups found for week {week}.", inline=False)
        return e

    groups = defaultdict(list)
    for entry in m:
        groups[entry.get("matchup_id")].append(entry)

    for mid, entries in sorted(groups.items()):
        if len(entries) == 2:
            a, b = entries
            a_name = roster_name.get(a.get("roster_id"), f"Roster {a.get('roster_id')}")
            b_name = roster_name.get(b.get("roster_id"), f"Roster {b.get('roster_id')}")
            a_pts = a.get("points", 0) or 0
            b_pts = b.get("points", 0) or 0
            value = f"{a_name} vs {b_name}\n(Current: {a_pts:.2f} – {b_pts:.2f})"
        else:
            e0 = entries[0]
            a_name = roster_name.get(e0.get("roster_id"), f"Roster {e0.get('roster_id')}")
            value = f"{a_name} (bye or unmatched)"
        add_kv(e, f"Matchup {mid}", value)
    return e

async def build_week_results_embed(lid: str, week: int) -> discord.Embed:
    users = await get_users(lid)
    rosters = await get_standings(lid)
    roster_name = _name_map(users, rosters)
    m = await get_matchups(lid, week)
    state = await get_nfl_state()
    current_week = int(state.get("week") or 1)

    title = f"Week {week} Results" + ("" if week < current_week else " (in progress)")
    e = card(title, color=SUCCESS if week < current_week else INFO)

    if not m:
        add_kv(e, "No data", f"No matchups found for week {week}.", inline=False)
        return e

    groups = defaultdict(list)
    for entry in m:
        groups[entry.get("matchup_id")].append(entry)

    for mid, entries in sorted(groups.items()):
        if len(entries) == 2:
            a, b = entries
            a_name = roster_name.get(a.get("roster_id"), f"Roster {a.get('roster_id')}")
            b_name = roster_name.get(b.get("roster_id"), f"Roster {b.get('roster_id')}")
            a_pts = float(a.get("points", 0) or 0)
            b_pts = float(b.get("points", 0) or 0)
            if a_pts > b_pts:
                value = f"👑 {a_name} {a_pts:.2f} — {b_pts:.2f} {b_name}"
            elif b_pts > a_pts:
                value = f"👑 {b_name} {b_pts:.2f} — {a_pts:.2f} {a_name}"
            else:
                value = f"🤝 {a_name} {a_pts:.2f} — {b_pts:.2f} {b_name} (tie)"
        else:
            e0 = entries[0]
            a_name = roster_name.get(e0.get("roster_id"), f"Roster {e0.get('roster_id')}")
            value = f"{a_name} (bye or unmatched)"
        add_kv(e, f"Matchup {mid}", value)
    return e

async def _post_weekly_preview():
    """Job: post upcoming week preview to default announce channel/role."""
    lid = league_id_effective()
    if not lid or not CFG.announce_channel_id:
        logger.warning("Preview job skipped: league_id or announce_channel missing.")
        return
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else discord.utils.get(bot.guilds)
    if not guild:
        logger.warning("Preview job skipped: guild not found.")
        return
    channel = guild.get_channel(CFG.announce_channel_id)
    if not channel:
        logger.warning("Preview job skipped: channel not found.")
        return

    state = await get_nfl_state()
    week = int(state.get("week") or 1)
    e = await build_week_preview_embed(lid, week)

    content = None
    allowed = discord.AllowedMentions.none()
    if CFG.announce_role_id:
        role = guild.get_role(CFG.announce_role_id)
        if role:
            content = role.mention
            allowed = discord.AllowedMentions(roles=True)
    await channel.send(content=content, embed=e, allowed_mentions=allowed)
    logger.info(f"Weekly preview posted to channel {CFG.announce_channel_id} for week {week}.")

async def _post_weekly_results():
    """Job: post last week's results (uses Tuesday mornings by default)."""
    lid = league_id_effective()
    if not lid or not CFG.announce_channel_id:
        logger.warning("Results job skipped: league_id or announce_channel missing.")
        return
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else discord.utils.get(bot.guilds)
    if not guild:
        logger.warning("Results job skipped: guild not found.")
        return
    channel = guild.get_channel(CFG.announce_channel_id)
    if not channel:
        logger.warning("Results job skipped: channel not found.")
        return

    state = await get_nfl_state()
    current_week = int(state.get("week") or 1)
    week = max(1, current_week - 1)  # post the week that just finished

    e = await build_week_results_embed(lid, week)

    content = None
    allowed = discord.AllowedMentions.none()
    if CFG.announce_role_id:
        role = guild.get_role(CFG.announce_role_id)
        if role:
            content = role.mention
            allowed = discord.AllowedMentions(roles=True)
    await channel.send(content=content, embed=e, allowed_mentions=allowed)
    logger.info(f"Weekly results posted to channel {CFG.announce_channel_id} for week {week}.")

def _register_preview_job(sched: AsyncIOScheduler):
    try:
        sched.remove_job("weekly_preview")
    except Exception:
        pass
    if not CFG.schedule_enabled:
        logger.info("Scheduler: weekly_preview disabled via config.")
        return
    trigger = CronTrigger(day_of_week=str(CFG.schedule_dow),
                          hour=CFG.schedule_hour,
                          minute=CFG.schedule_minute,
                          timezone=TZ)
    sched.add_job(_post_weekly_preview, trigger=trigger, id="weekly_preview")
    logger.info(f"Scheduler: weekly_preview enabled at DOW={CFG.schedule_dow} {CFG.schedule_hour:02d}:{CFG.schedule_minute:02d} ET.")

def _register_results_job(sched: AsyncIOScheduler):
    try:
        sched.remove_job("weekly_results")
    except Exception:
        pass
    if not getattr(CFG, "results_enabled", False):
        logger.info("Scheduler: weekly_results disabled via config.")
        return
    trigger = CronTrigger(day_of_week=str(CFG.results_dow),
                          hour=CFG.results_hour,
                          minute=CFG.results_minute,
                          timezone=TZ)
    sched.add_job(_post_weekly_results, trigger=trigger, id="weekly_results")
    logger.info(f"Scheduler: weekly_results enabled at DOW={CFG.results_dow} {CFG.results_hour:02d}:{CFG.results_minute:02d} ET.")

# ---------- Commands ----------

@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(embed=card("Pong! 🏓", color=SUCCESS))

@bot.tree.command(name="league", description="Show basic Sleeper league info.")
async def league(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    lid = league_id_effective()
    if not lid:
        await interaction.followup.send(embed=card("Not configured", "No league ID set. Use /config set league_id.", WARN))
        return
    data = await get_league(lid)
    name = data.get("name", "Unknown League")
    season = data.get("season", "Unknown")
    total_rosters = data.get("total_rosters", "N/A")
    e = card(title=name, desc=f"Season **{season}**", color=PRIMARY)
    add_kv(e, "Total Rosters", str(total_rosters))
    e.set_footer(text=f"League ID: {lid}")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="standings", description="Show league standings.")
async def standings(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    lid = league_id_effective()
    if not lid:
        await interaction.followup.send(embed=card("Not configured", "No league ID set. Use /config set league_id.", WARN))
        return
    rosters = await get_standings(lid)
    sorted_rosters = sorted(
        rosters,
        key=lambda r: (
            r.get("settings", {}).get("wins", 0),
            r.get("settings", {}).get("fpts", 0),
        ),
        reverse=True,
    )
    e = card("League Standings", color=INFO)
    for i, r in enumerate(sorted_rosters, start=1):
        s = r.get("settings", {}) or {}
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        points = s.get("fpts", 0)
        add_kv(e, f"#{i} — Roster {r.get('roster_id')}", f"Wins: {wins} | Losses: {losses} | Points: {points}")
    await interaction.followup.send(embed=e)

@bot.tree.command(name="schedule", description="Show matchups for a given week (defaults to current).")
@app_commands.describe(week="NFL week number (optional)")
async def schedule(interaction: discord.Interaction, week: int | None = None):
    await interaction.response.defer(thinking=True)
    lid = league_id_effective()
    if not lid:
        await interaction.followup.send(embed=card("Not configured", "No league ID set. Use /config set league_id.", WARN))
        return
    if week is None:
        state = await get_nfl_state()
        week = int(state.get("week") or 1)
    e = await build_week_preview_embed(lid, week)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="results", description="Show final (or current) results for a given week.")
@app_commands.describe(week="NFL week number (optional)")
async def results(interaction: discord.Interaction, week: int | None = None):
    await interaction.response.defer(thinking=True)
    lid = league_id_effective()
    if not lid:
        await interaction.followup.send(embed=card("Not configured", "No league ID set. Use /config set league_id.", WARN))
        return
    state = await get_nfl_state()
    current_week = int(state.get("week") or 1)
    if week is None:
        week = current_week
    e = await build_week_results_embed(lid, week)
    await interaction.followup.send(embed=e)

# ----- Admin-only: announce + manual preview/results -----

def _is_commissioner_decorator():
    def predicate(interaction: discord.Interaction) -> bool:
        return commissioner_check(interaction)
    return app_commands.check(predicate)

@bot.tree.command(name="announce", description="(Commissioner only) Post an announcement to a channel.")
@_is_commissioner_decorator()
@app_commands.describe(
    channel="Target channel (optional, uses config default if omitted)",
    title="Headline for the card",
    body="Main announcement text",
    role="Optional role to ping (uses config default if omitted)",
    ping="If true, tag the role",
    image_url="Optional image URL"
)
async def announce(
    interaction: discord.Interaction,
    title: str,
    body: str,
    channel: discord.TextChannel | None = None,
    role: discord.Role | None = None,
    ping: bool = False,
    image_url: str | None = None,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        target_channel = channel or (interaction.guild.get_channel(CFG.announce_channel_id) if CFG.announce_channel_id else None)
        if not target_channel:
            await interaction.followup.send(embed=card("Missing channel", "Provide channel: or set a default via /config set announce_channel.", WARN), ephemeral=True)
            return

        target_role = role or (interaction.guild.get_role(CFG.announce_role_id) if CFG.announce_role_id else None)

        e = card(title, body, color=PRIMARY)
        if image_url:
            try:
                e.set_image(url=image_url)
            except Exception:
                pass

        content = None
        allowed = discord.AllowedMentions.none()
        if ping and target_role is not None:
            content = target_role.mention
            allowed = discord.AllowedMentions(roles=True)

        msg = await target_channel.send(content=content, embed=e, allowed_mentions=allowed)
        await interaction.followup.send(embed=card("Announcement sent ✅", f"Posted to {target_channel.mention}\n[Jump to message]({msg.jump_url})", SUCCESS), ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(embed=card("Permission error", "I don't have permission to post in that channel.", ERROR), ephemeral=True)
    except Exception as ex:
        await interaction.followup.send(embed=card("Error sending announcement", f"{ex}", ERROR), ephemeral=True)

@bot.tree.command(name="announce_preview", description="(Commissioner only) Manually post this week's preview to default channel.")
@_is_commissioner_decorator()
async def announce_preview(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    lid = league_id_effective()
    if not lid or not CFG.announce_channel_id:
        await interaction.followup.send(embed=card("Not configured", "Set league_id and nnounce_channel in /config set.", WARN), ephemeral=True)
        return
    guild = interaction.guild
    channel = guild.get_channel(CFG.announce_channel_id)
    if not channel:
        await interaction.followup.send(embed=card("Channel not found", "Update /config set announce_channel.", WARN), ephemeral=True)
        return
    state = await get_nfl_state()
    week = int(state.get("week") or 1)
    e = await build_week_preview_embed(lid, week)

    content = None
    allowed = discord.AllowedMentions.none()
    if CFG.announce_role_id:
        role = guild.get_role(CFG.announce_role_id)
        if role:
            content = role.mention
            allowed = discord.AllowedMentions(roles=True)

    msg = await channel.send(content=content, embed=e, allowed_mentions=allowed)
    await interaction.followup.send(embed=card("Preview sent ✅", f"Posted to {channel.mention}\n[Jump to message]({msg.jump_url})", SUCCESS), ephemeral=True)

@bot.tree.command(name="announce_results", description="(Commissioner only) Manually post last week's results to default channel.")
@_is_commissioner_decorator()
async def announce_results(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    lid = league_id_effective()
    if not lid or not CFG.announce_channel_id:
        await interaction.followup.send(embed=card("Not configured", "Set league_id and nnounce_channel in /config set.", WARN), ephemeral=True)
        return
    guild = interaction.guild
    channel = guild.get_channel(CFG.announce_channel_id)
    if not channel:
        await interaction.followup.send(embed=card("Channel not found", "Update /config set announce_channel.", WARN), ephemeral=True)
        return
    state = await get_nfl_state()
    current_week = int(state.get("week") or 1)
    week = max(1, current_week - 1)
    e = await build_week_results_embed(lid, week)

    content = None
    allowed = discord.AllowedMentions.none()
    if CFG.announce_role_id:
        role = guild.get_role(CFG.announce_role_id)
        if role:
            content = role.mention
            allowed = discord.AllowedMentions(roles=True)

    msg = await channel.send(content=content, embed=e, allowed_mentions=allowed)
    await interaction.followup.send(embed=card("Results sent ✅", f"Posted to {channel.mention}\n[Jump to message]({msg.jump_url})", SUCCESS), ephemeral=True)

# ---------- /config (commissioner only) ----------

class ConfigGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="config", description="Commissioner-only bot configuration.")

config_group = ConfigGroup()
bot.tree.add_command(config_group)

@config_group.command(name="get", description="Show current configuration.")
@_is_commissioner_decorator()
async def config_get(interaction: discord.Interaction):
    e = card("Current Configuration", color=PRIMARY)
    add_kv(e, "league_id", str(CFG.league_id or ENV_LEAGUE_ID or "—"))
    add_kv(e, "announce_channel_id", str(CFG.announce_channel_id or "—"))
    add_kv(e, "announce_role_id", str(CFG.announce_role_id or "—"))
    add_kv(e, "default_days", str(CFG.default_days))
    # preview schedule
    add_kv(e, "schedule_enabled", str(CFG.schedule_enabled))
    add_kv(e, "schedule_dow", str(CFG.schedule_dow))
    add_kv(e, "schedule_hour", str(CFG.schedule_hour))
    add_kv(e, "schedule_minute", str(CFG.schedule_minute))
    # results schedule
    add_kv(e, "results_enabled", str(getattr(CFG, "results_enabled", False)))
    add_kv(e, "results_dow", str(getattr(CFG, "results_dow", 1)))
    add_kv(e, "results_hour", str(getattr(CFG, "results_hour", 9)))
    add_kv(e, "results_minute", str(getattr(CFG, "results_minute", 0)))
    await interaction.response.send_message(embed=e, ephemeral=True)

@config_group.command(name="set", description="Update a configuration value.")
@_is_commissioner_decorator()
@app_commands.describe(
    league_id="Sleeper League ID",
    announce_channel="Default channel for announcements",
    announce_role="Default role to ping",
    default_days="Default transaction lookback in days",
    schedule_enabled="Enable weekly preview job?",
    schedule_dow="Day of week (0=Mon … 6=Sun)",
    schedule_hour="Hour (ET, 0-23)",
    schedule_minute="Minute (0-59)",
    results_enabled="Enable weekly results job?",
    results_dow="Day of week (0=Mon … 6=Sun; Tuesday=1)",
    results_hour="Hour (ET, 0-23)",
    results_minute="Minute (0-59)",
)
async def config_set(
    interaction: discord.Interaction,
    league_id: str | None = None,
    announce_channel: discord.TextChannel | None = None,
    announce_role: discord.Role | None = None,
    default_days: int | None = None,
    schedule_enabled: bool | None = None,
    schedule_dow: int | None = None,
    schedule_hour: int | None = None,
    schedule_minute: int | None = None,
    results_enabled: bool | None = None,
    results_dow: int | None = None,
    results_hour: int | None = None,
    results_minute: int | None = None,
):
    changed = []
    if league_id is not None:
        CFG.league_id = league_id.strip()
        changed.append("league_id")
    if announce_channel is not None:
        CFG.announce_channel_id = announce_channel.id
        changed.append("announce_channel_id")
    if announce_role is not None:
        CFG.announce_role_id = announce_role.id
        changed.append("announce_role_id")
    if default_days is not None:
        CFG.default_days = max(1, min(60, int(default_days)))
        changed.append("default_days")
    if schedule_enabled is not None:
        CFG.schedule_enabled = bool(schedule_enabled)
        changed.append("schedule_enabled")
    if schedule_dow is not None:
        CFG.schedule_dow = max(0, min(6, int(schedule_dow)))
        changed.append("schedule_dow")
    if schedule_hour is not None:
        CFG.schedule_hour = max(0, min(23, int(schedule_hour)))
        changed.append("schedule_hour")
    if schedule_minute is not None:
        CFG.schedule_minute = max(0, min(59, int(schedule_minute)))
        changed.append("schedule_minute")
    if results_enabled is not None:
        CFG.results_enabled = bool(results_enabled)
        changed.append("results_enabled")
    if results_dow is not None:
        CFG.results_dow = max(0, min(6, int(results_dow)))
        changed.append("results_dow")
    if results_hour is not None:
        CFG.results_hour = max(0, min(23, int(results_hour)))
        changed.append("results_hour")
    if results_minute is not None:
        CFG.results_minute = max(0, min(59, int(results_minute)))
        changed.append("results_minute")

    save_config(CFG)

    # (Re)register jobs with latest config
    if bot.scheduler:
        _register_preview_job(bot.scheduler)
        _register_results_job(bot.scheduler)

    if not changed:
        await interaction.response.send_message(embed=card("No changes", "Provide at least one field to update.", WARN), ephemeral=True)
        return

    e = card("Config updated ✅", color=SUCCESS)
    add_kv(e, "Changed", ", ".join(changed))
    await interaction.response.send_message(embed=e, ephemeral=True)

def main():
    token = TOKEN
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing. Set it in .env")
    bot.run(token)

if __name__ == "__main__":
    main()
