# ============================================================
#  Echelon League Bot — auto_images.py
#  Version: 1.0.0
#  NEW COG — never modifies any existing file.
#
#  Automatically refreshes league images when new matches are
#  detected. Mirrors the same poll pattern used in results.py.
#
#  Images refreshed:
#    • Standings        → standings_channel_id (shared w/ standings.py)
#    • League Leaders   → leaders_channel_id
#    • Rosters          → rosters_channel_id
#    • Team Cards       → team_cards_channel_id  (one per team)
#
#  Data source: Google Sheets first, stats.json fallback.
#
#  Setup commands (admin only):
#    /setleaderschannel     — pin current channel for leaders image
#    /setrosterschannel     — pin current channel for rosters image
#    /setteamcardschannel   — pin current channel for team cards
#    /autorefresh           — force a manual refresh of all images now
#
#  NOTE: Standings channel is shared with standings.py which uses
#  the key "standings_channel_id" — this cog reads that same key
#  so you only need to run /setstandingschannel once.
#
#  Changelog:
#    v1.0.0 - Initial release.
#             Poll-based detection (5 min) via Game Results tab.
#             Sheets-first / stats.json fallback data loading.
#             trigger_refresh() public hook for results.py.
#             Per-image message tracking so old posts are replaced.
#             No existing cog or utils.py modified.
# ============================================================

VERSION  = "1.0.0"
COG_NAME = "AutoImages"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Auto Image Refresh Engine")

import io
import os
import json
import asyncio

import discord
from discord.ext import commands, tasks
from discord import app_commands

import utils

POLL_INTERVAL_MINUTES = 5
GAME_RESULTS_TAB      = "Game Results"
STATS_JSON_PATH       = os.path.join(utils.BASE_DIR, "stats.json")

# Config keys used to persist channel IDs and last-message IDs
_KEY_LEADERS_CHAN    = "leaders_channel_id"
_KEY_ROSTERS_CHAN    = "rosters_channel_id"
_KEY_TEAMCARDS_CHAN  = "team_cards_channel_id"
_KEY_STANDINGS_CHAN  = "standings_channel_id"   # shared with standings.py

_KEY_LEADERS_MSG    = "auto_leaders_message_id"
_KEY_ROSTERS_MSG    = "auto_rosters_message_id"
_KEY_TEAMCARDS_MSG  = "auto_team_cards_message_id"   # dict: {team_id: msg_id}
_KEY_STANDINGS_MSG  = "auto_standings_message_id"


# ════════════════════════════════════════════════════════════
#  DATA LOADERS  (Sheets-first, JSON fallback)
# ════════════════════════════════════════════════════════════

def _load_json_stats() -> dict:
    """Load stats.json produced by web_export.py. Returns {} on failure."""
    try:
        if os.path.exists(STATS_JSON_PATH):
            with open(STATS_JSON_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[{COG_NAME}] stats.json read failed: {e}")
    return {}


def _season_stats_from_json(jdata: dict) -> dict:
    """
    Convert stats.json skater/goalie arrays into the same dict format
    that utils.get_season_stats_from_sheet() returns.
    Expected keys in stats.json: 'skaters', 'goalies' (list of player dicts).
    Falls back gracefully if keys are missing.
    """
    stats = {}
    for player in jdata.get("skaters", []):
        name = player.get("Username") or player.get("username") or player.get("name")
        if not name:
            continue
        stats[name] = {
            "GP":            int(player.get("GP", 0)),
            "G":             int(player.get("G", 0)),
            "A":             int(player.get("A", 0)),
            "P":             int(player.get("P", player.get("PTS", 0))),
            "Hits":          int(player.get("Hits", 0)),
            "S":             int(player.get("S", 0)),
            "PIM":           int(player.get("PIM", 0)),
            "+/-":           int(player.get("+/-", 0)),
            "Sv":            0,
            "GA":            0,
            "Save % Value":  0.0,
            "Main Position": "Skater",
        }
    for player in jdata.get("goalies", []):
        name = player.get("Username") or player.get("username") or player.get("name")
        if not name:
            continue
        sv  = int(player.get("Sv", player.get("Saves", 0)))
        ga  = int(player.get("GA", player.get("Goals Against", 0)))
        sa  = sv + ga
        stats[name] = {
            "GP":            int(player.get("GP", 0)),
            "G":             int(player.get("G", 0)),
            "A":             int(player.get("A", 0)),
            "P":             int(player.get("P", player.get("PTS", 0))),
            "Hits":          0,
            "S":             0,
            "PIM":           int(player.get("PIM", 0)),
            "+/-":           0,
            "Sv":            sv,
            "GA":            ga,
            "Save % Value":  (sv / sa) if sa > 0 else 0.0,
            "Main Position": "Goalie",
        }
    return stats


def _roster_data_from_json(jdata: dict, config: dict) -> dict:
    """
    Build the same roster dict that utils.get_roster_data_from_sheet() returns:
        { team_id: { player_name: gp } }
    stats.json 'rosters' section is expected as:
        { team_name: [ {name, gp}, ... ] }  OR  { team_id: [...] }
    """
    rosters = {str(tid): {} for tid in config.get("team_ids", {})}
    raw = jdata.get("rosters", {})
    # Build reverse name→id map
    name_to_id = {v.lower(): k for k, v in config.get("team_ids", {}).items()}
    for key, players in raw.items():
        tid = str(key) if str(key) in rosters else name_to_id.get(str(key).lower())
        if not tid:
            continue
        for p in players:
            pname = p.get("name") or p.get("username") or p.get("Username")
            gp    = int(p.get("GP", p.get("gp", 0)))
            if pname:
                rosters[tid][pname] = gp
    return rosters


def _get_season_stats(config: dict) -> dict:
    """Sheets first; stats.json fallback."""
    try:
        result = utils.get_season_stats_from_sheet(config)
        if result:
            return result
    except Exception as e:
        print(f"[{COG_NAME}] Sheets season stats failed: {e}")
    print(f"[{COG_NAME}] Falling back to stats.json for season stats.")
    return _season_stats_from_json(_load_json_stats())


def _get_roster_data(config: dict) -> dict:
    """Sheets first; stats.json fallback."""
    try:
        result = utils.get_roster_data_from_sheet(config)
        if result:
            return result
    except Exception as e:
        print(f"[{COG_NAME}] Sheets roster data failed: {e}")
    print(f"[{COG_NAME}] Falling back to stats.json for rosters.")
    return _roster_data_from_json(_load_json_stats(), config)


def _get_standings_rows(sh) -> list:
    """
    Read the Game Results tab and compute standings rows.
    Returns list of [Rank, Name, GP, W, L, OTL, PTS, GF, GA, Diff]
    — identical to what standings.py/_calc_standings() does.
    We duplicate the logic here to avoid importing the cog directly.
    """
    try:
        ws   = sh.worksheet(GAME_RESULTS_TAB)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] Could not read Game Results: {e}")
        return []

    if len(rows) < 2:
        return []

    teams: dict = {}

    def _ensure(name):
        if name not in teams:
            teams[name] = {"GP": 0, "W": 0, "L": 0, "OTL": 0,
                           "GF": 0, "GA": 0, "PTS": 0}

    def _si(val):
        try:    return int(str(val).strip())
        except: return 0

    for row in rows[1:]:
        if len(row) < 8:
            continue
        t1, s1, r1 = str(row[2]).strip(), _si(row[3]), str(row[4]).strip().upper()
        t2, s2, r2 = str(row[5]).strip(), _si(row[6]), str(row[7]).strip().upper()
        if not t1 or not t2:
            continue
        _ensure(t1); _ensure(t2)
        teams[t1]["GP"] += 1; teams[t2]["GP"] += 1
        teams[t1]["GF"] += s1; teams[t1]["GA"] += s2
        teams[t2]["GF"] += s2; teams[t2]["GA"] += s1
        for result, tname in [(r1, t1), (r2, t2)]:
            if result in ("W", "W-FF", "OTW"):
                teams[tname]["W"]   += 1; teams[tname]["PTS"] += 2
            elif result == "OTL":
                teams[tname]["OTL"] += 1; teams[tname]["PTS"] += 1
            else:
                teams[tname]["L"]   += 1

    if not teams:
        return []

    sorted_teams = sorted(
        teams.items(),
        key=lambda x: (x[1]["PTS"], x[1]["W"], x[1]["GF"] - x[1]["GA"]),
        reverse=True,
    )
    return [
        [rank, name, s["GP"], s["W"], s["L"],
         s["OTL"], s["PTS"], s["GF"], s["GA"], s["GF"] - s["GA"]]
        for rank, (name, s) in enumerate(sorted_teams, 1)
    ]


def _get_match_id_set(sh) -> set:
    """Returns the set of Match IDs currently in the Game Results tab."""
    try:
        ws  = sh.worksheet(GAME_RESULTS_TAB)
        col = ws.col_values(1)
        return {v.strip() for v in col[1:] if v.strip()}
    except Exception as e:
        print(f"[{COG_NAME}] Match ID read failed: {e}")
        return set()


# ════════════════════════════════════════════════════════════
#  POST / REPLACE HELPERS
# ════════════════════════════════════════════════════════════

async def _replace_message(channel: discord.TextChannel, old_msg_id: int | None,
                            content: str, file_buf: io.BytesIO,
                            filename: str) -> int | None:
    """Delete old pinned image message, post new one. Returns new message ID."""
    if old_msg_id:
        try:
            old = await channel.fetch_message(int(old_msg_id))
            await old.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    ts = int(discord.utils.utcnow().timestamp())
    try:
        msg = await channel.send(
            content=f"{content}\n*Last updated: <t:{ts}:R>*",
            file=discord.File(fp=file_buf, filename=filename),
        )
        return msg.id
    except Exception as e:
        print(f"[{COG_NAME}] Failed to post {filename}: {e}")
        return None


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class AutoImages(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot             = bot
        self._known_ids: set = set()
        print(f"🖼️  [{COG_NAME}] Cog initialized — v{VERSION}")

    async def cog_load(self):
        self._poll_loop.start()
        print(f"⏱️  [{COG_NAME}] Poll loop started ({POLL_INTERVAL_MINUTES} min interval)")

    async def cog_unload(self):
        self._poll_loop.cancel()

    # ── channel helpers ──────────────────────────────────────

    def _chan(self, key: str) -> discord.TextChannel | None:
        cid = self.bot.config.get(key, 0)
        return self.bot.get_channel(int(cid)) if cid else None

    # ── core refresh ─────────────────────────────────────────

    async def _refresh_all(self):
        """
        Build and post all four image types.
        Each image is independent — a failure in one does not block others.
        All blocking sheet/image calls run in executor.
        """
        loop = asyncio.get_event_loop()
        config = self.bot.config

        print(f"[{COG_NAME}] Starting full image refresh...")

        # ── 1. STANDINGS ─────────────────────────────────────
        chan_s = self._chan(_KEY_STANDINGS_CHAN)
        if chan_s:
            try:
                sh = await loop.run_in_executor(None, utils.get_sheet)
                if sh:
                    rows = await loop.run_in_executor(None, _get_standings_rows, sh)
                    if rows:
                        buf = await loop.run_in_executor(
                            None, utils.generate_standings_image, rows
                        )
                        buf.seek(0)
                        old = config.get(_KEY_STANDINGS_MSG)
                        new_id = await _replace_message(
                            chan_s, old,
                            "🏒 **OS4 League Standings**", buf,
                            "standings.png"
                        )
                        if new_id:
                            config[_KEY_STANDINGS_MSG] = str(new_id)
                            utils.save_config(config)
                            print(f"[{COG_NAME}] ✅ Standings refreshed (msg {new_id})")
                    else:
                        print(f"[{COG_NAME}] ⚠️ Standings: no data rows returned.")
                else:
                    print(f"[{COG_NAME}] ⚠️ Standings: sheet connection failed.")
            except Exception as e:
                print(f"[{COG_NAME}] ❌ Standings error: {e}")
        else:
            print(f"[{COG_NAME}] ℹ️  No standings channel set — skipping.")

        # ── 2. LEAGUE LEADERS ────────────────────────────────
        chan_l = self._chan(_KEY_LEADERS_CHAN)
        if chan_l:
            try:
                season_stats = await loop.run_in_executor(
                    None, _get_season_stats, config
                )
                if season_stats:
                    buf = await loop.run_in_executor(
                        None, utils.generate_leaderboard_image, season_stats
                    )
                    buf.seek(0)
                    old = config.get(_KEY_LEADERS_MSG)
                    new_id = await _replace_message(
                        chan_l, old,
                        "🏆 **League Leaders**", buf,
                        "leaders.png"
                    )
                    if new_id:
                        config[_KEY_LEADERS_MSG] = str(new_id)
                        utils.save_config(config)
                        print(f"[{COG_NAME}] ✅ Leaders refreshed (msg {new_id})")
                else:
                    print(f"[{COG_NAME}] ⚠️ Leaders: no season stats returned.")
            except Exception as e:
                print(f"[{COG_NAME}] ❌ Leaders error: {e}")
        else:
            print(f"[{COG_NAME}] ℹ️  No leaders channel set — skipping.")

        # ── 3. ROSTERS ───────────────────────────────────────
        chan_r = self._chan(_KEY_ROSTERS_CHAN)
        if chan_r:
            try:
                roster_data = await loop.run_in_executor(
                    None, _get_roster_data, config
                )
                if any(v for v in roster_data.values()):
                    buf = await loop.run_in_executor(
                        None, utils.generate_roster_image, roster_data, config
                    )
                    buf.seek(0)
                    old = config.get(_KEY_ROSTERS_MSG)
                    new_id = await _replace_message(
                        chan_r, old,
                        "📋 **Team Rosters**", buf,
                        "rosters.png"
                    )
                    if new_id:
                        config[_KEY_ROSTERS_MSG] = str(new_id)
                        utils.save_config(config)
                        print(f"[{COG_NAME}] ✅ Rosters refreshed (msg {new_id})")
                else:
                    print(f"[{COG_NAME}] ⚠️ Rosters: no data returned.")
            except Exception as e:
                print(f"[{COG_NAME}] ❌ Rosters error: {e}")
        else:
            print(f"[{COG_NAME}] ℹ️  No rosters channel set — skipping.")

        # ── 4. TEAM CARDS (one per configured team) ──────────
        chan_tc = self._chan(_KEY_TEAMCARDS_CHAN)
        if chan_tc:
            try:
                season_stats = await loop.run_in_executor(
                    None, _get_season_stats, config
                )
                roster_data = await loop.run_in_executor(
                    None, _get_roster_data, config
                )
                # Load existing per-team message IDs (stored as JSON string in config)
                tc_msg_map: dict = {}
                raw = config.get(_KEY_TEAMCARDS_MSG)
                if raw:
                    try:
                        tc_msg_map = json.loads(raw) if isinstance(raw, str) else raw
                    except Exception:
                        tc_msg_map = {}

                for tid, tname in config.get("team_ids", {}).items():
                    roster_names = roster_data.get(str(tid), {})
                    if not roster_names:
                        continue
                    roster_stats = [
                        (name, season_stats[name])
                        for name in roster_names
                        if name in season_stats
                    ]
                    if not roster_stats:
                        continue
                    try:
                        buf = await loop.run_in_executor(
                            None, utils.generate_wide_team_card, tname, roster_stats
                        )
                        buf.seek(0)
                        old_tc = tc_msg_map.get(str(tid))
                        new_id = await _replace_message(
                            chan_tc, old_tc,
                            f"🏒 **{tname} — Team Stats**", buf,
                            f"team_card_{tid}.png"
                        )
                        if new_id:
                            tc_msg_map[str(tid)] = str(new_id)
                            print(f"[{COG_NAME}] ✅ Team card: {tname} (msg {new_id})")
                    except Exception as e:
                        print(f"[{COG_NAME}] ❌ Team card error ({tname}): {e}")

                config[_KEY_TEAMCARDS_MSG] = json.dumps(tc_msg_map)
                utils.save_config(config)

            except Exception as e:
                print(f"[{COG_NAME}] ❌ Team cards outer error: {e}")
        else:
            print(f"[{COG_NAME}] ℹ️  No team cards channel set — skipping.")

        print(f"[{COG_NAME}] Full image refresh complete.")

    # ── public hook ──────────────────────────────────────────

    async def trigger_refresh(self):
        """
        Call this from results.py (or any cog) after new games are logged
        to immediately push updated images without waiting for the poll.

        Usage in results.py after writing Game Results tab:
            auto_cog = self.bot.get_cog("AutoImages")
            if auto_cog:
                await auto_cog.trigger_refresh()
        """
        print(f"[{COG_NAME}] trigger_refresh() called — running full refresh now.")
        try:
            await self._refresh_all()
        except Exception as e:
            print(f"[{COG_NAME}] trigger_refresh error: {e}")

    # ── background poll ──────────────────────────────────────

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def _poll_loop(self):
        """
        Every 5 minutes: check if any new Match IDs appeared in
        the Game Results tab. Only triggers a full refresh on change,
        keeping sheet reads to a minimum when nothing is happening.
        """
        try:
            loop = asyncio.get_event_loop()
            sh = await loop.run_in_executor(None, utils.get_sheet)
            if not sh:
                return

            current_ids = await loop.run_in_executor(None, _get_match_id_set, sh)

            # On first run just seed the known set — don't refresh yet
            if not self._known_ids:
                self._known_ids = current_ids
                print(f"[{COG_NAME}] Poll seeded with {len(current_ids)} match IDs.")
                return

            new_ids = current_ids - self._known_ids
            if new_ids:
                print(f"[{COG_NAME}] Poll: {len(new_ids)} new match(es) detected — triggering refresh.")
                self._known_ids = current_ids
                await self._refresh_all()
            # else: nothing changed, do nothing

        except Exception as e:
            print(f"[{COG_NAME}] Poll loop error: {e}")

    @_poll_loop.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    # ── setup commands ───────────────────────────────────────

    @app_commands.command(
        name="setleaderschannel",
        description="[Admin] Set this channel as the auto-refreshing League Leaders image channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setleaderschannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.config[_KEY_LEADERS_CHAN] = interaction.channel_id
        # Clear saved message ID so first post lands in the new channel
        self.bot.config.pop(_KEY_LEADERS_MSG, None)
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ League Leaders channel set to <#{interaction.channel_id}>.\n"
            f"Run `/autorefresh` to post the first image.",
            ephemeral=True
        )
        print(f"[{COG_NAME}] Leaders channel → {interaction.channel_id}")

    @app_commands.command(
        name="setrosterschannel",
        description="[Admin] Set this channel as the auto-refreshing Rosters image channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setrosterschannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.config[_KEY_ROSTERS_CHAN] = interaction.channel_id
        self.bot.config.pop(_KEY_ROSTERS_MSG, None)
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ Rosters channel set to <#{interaction.channel_id}>.\n"
            f"Run `/autorefresh` to post the first image.",
            ephemeral=True
        )
        print(f"[{COG_NAME}] Rosters channel → {interaction.channel_id}")

    @app_commands.command(
        name="setteamcardschannel",
        description="[Admin] Set this channel as the auto-refreshing Team Cards image channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setteamcardschannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.config[_KEY_TEAMCARDS_CHAN] = interaction.channel_id
        self.bot.config.pop(_KEY_TEAMCARDS_MSG, None)
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ Team Cards channel set to <#{interaction.channel_id}>.\n"
            f"Run `/autorefresh` to post the first image.",
            ephemeral=True
        )
        print(f"[{COG_NAME}] Team Cards channel → {interaction.channel_id}")

    @app_commands.command(
        name="autorefresh",
        description="[Admin] Force an immediate refresh of all auto-image channels."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def autorefresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "🔄 Refreshing all auto-images now...", ephemeral=True
        )
        try:
            await self._refresh_all()
            await interaction.edit_original_response(
                content="✅ All auto-images refreshed successfully."
            )
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Refresh error: `{e}`")

    # ── error handlers ───────────────────────────────────────

    @setleaderschannel.error
    @setrosterschannel.error
    @setteamcardschannel.error
    @autorefresh.error
    async def _admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Error: `{error}`", ephemeral=True)


# ════════════════════════════════════════════════════════════
#  SETUP
# ════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoImages(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
