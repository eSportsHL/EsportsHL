# ============================================================
#  OS4 League Bot — standings_board.py
#  Version: 1.1.0
#    - No fixed timer — refresh is event-driven
#    - Trigger 1: gameresults.py calls trigger_refresh() after /updateresults
#    - Trigger 2: 5-min poll detects new match IDs in Game Results tab
#  Brand new cog — zero existing code modified
# ============================================================

VERSION  = "1.1.0"
COG_NAME = "StandingsBoard"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading...")

import io
import discord
from discord.ext import commands, tasks
from discord import app_commands
import utils

POLL_INTERVAL_MINUTES = 5
GAME_RESULTS_TAB = "Game Results"


# ════════════════════════════════════════════════════════════
#  STANDINGS CALCULATOR
# ════════════════════════════════════════════════════════════

def _calc_standings(sh, team_names: dict) -> list:
    """
    Reads the 'Game Results' tab → returns sorted standings rows:
      [Rank, Team Name, GP, W, L, OTL, PTS, GF, GA, Diff]
    Result strings from gameresults.py:
      W / W-FF / OTW  → 2 pts
      OTL             → 1 pt
      L / L-FF        → 0 pts
    """
    try:
        ws = sh.worksheet(GAME_RESULTS_TAB)
        all_rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] Could not read '{GAME_RESULTS_TAB}': {e}")
        return []

    if len(all_rows) < 2:
        return []

    teams: dict = {}

    def _ensure(name):
        if name not in teams:
            teams[name] = {"GP": 0, "W": 0, "L": 0, "OTL": 0,
                           "GF": 0, "GA": 0, "PTS": 0}

    def _safe_int(val):
        try:
            return int(str(val).strip())
        except (ValueError, TypeError):
            return 0

    for row in all_rows[1:]:
        if len(row) < 10:
            continue
        t1_name   = str(row[2]).strip()
        score_t1  = _safe_int(row[3])
        result_t1 = str(row[4]).strip().upper()
        t2_name   = str(row[5]).strip()
        score_t2  = _safe_int(row[6])
        result_t2 = str(row[7]).strip().upper()

        if not t1_name or not t2_name:
            continue

        _ensure(t1_name)
        _ensure(t2_name)

        teams[t1_name]["GP"] += 1
        teams[t2_name]["GP"] += 1
        teams[t1_name]["GF"] += score_t1
        teams[t1_name]["GA"] += score_t2
        teams[t2_name]["GF"] += score_t2
        teams[t2_name]["GA"] += score_t1

        for result, tname in [(result_t1, t1_name), (result_t2, t2_name)]:
            if result in ("W", "W-FF", "OTW"):
                teams[tname]["W"]   += 1
                teams[tname]["PTS"] += 2
            elif result == "OTL":
                teams[tname]["OTL"] += 1
                teams[tname]["PTS"] += 1
            else:
                teams[tname]["L"] += 1

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


def _get_match_ids(sh) -> set:
    """Returns the set of Match IDs in the Game Results tab."""
    try:
        ws = sh.worksheet(GAME_RESULTS_TAB)
        col = ws.col_values(1)
        return {v.strip() for v in col[1:] if v.strip()}
    except Exception as e:
        print(f"[{COG_NAME}] Could not read match IDs: {e}")
        return set()


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class StandingsBoard(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._standings_message_id: int | None = None
        self._known_match_ids: set = set()
        print(f"🏆 [{COG_NAME}] Cog initialized — v{VERSION}")

    async def cog_load(self):
        self._poll_loop.start()
        print(f"⏱️  [{COG_NAME}] Poll loop started (every {POLL_INTERVAL_MINUTES} min)")

    async def cog_unload(self):
        self._poll_loop.cancel()

    # ── helpers ──────────────────────────────────────────────

    def _get_standings_channel(self) -> discord.TextChannel | None:
        cid = self.bot.config.get("standings_channel_id", 0)
        if not cid:
            return None
        return self.bot.get_channel(int(cid))

    async def _build_image_file(self) -> discord.File | None:
        sh = utils.get_sheet()
        if not sh:
            print(f"[{COG_NAME}] Sheet connection failed.")
            return None
        rows = _calc_standings(sh, self.bot.config.get("team_ids", {}))
        if not rows:
            print(f"[{COG_NAME}] No standings data.")
            return None
        buf: io.BytesIO = utils.generate_standings_image(rows)
        buf.seek(0)
        return discord.File(buf, filename="os4_standings.png")

    async def _post_or_refresh(self, channel: discord.TextChannel):
        img_file = await self._build_image_file()
        if not img_file:
            return
        if self._standings_message_id:
            try:
                old = await channel.fetch_message(self._standings_message_id)
                await old.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            self._standings_message_id = None
        ts = int(discord.utils.utcnow().timestamp())
        sent = await channel.send(
            content=f"🏒 **OS4 League Standings**\n*Last updated: <t:{ts}:R>*",
            file=img_file,
        )
        self._standings_message_id = sent.id
        print(f"[{COG_NAME}] Standings refreshed (msg {sent.id})")

    # ── public hook called by gameresults.py ─────────────────

    async def trigger_refresh(self):
        """Called by gameresults.py after /updateresults writes the sheet."""
        channel = self._get_standings_channel()
        if not channel:
            print(f"[{COG_NAME}] trigger_refresh: no standings channel configured.")
            return
        print(f"[{COG_NAME}] trigger_refresh() — refreshing standings now.")
        try:
            await self._post_or_refresh(channel)
        except Exception as e:
            print(f"[{COG_NAME}] trigger_refresh error: {e}")

    # ── background poll (safety net) ─────────────────────────

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def _poll_loop(self):
        """Detects new match IDs in the sheet. Only refreshes on change."""
        channel = self._get_standings_channel()
        if not channel:
            return
        try:
            sh = utils.get_sheet()
            if not sh:
                return
            current_ids = _get_match_ids(sh)
            if not self._known_match_ids:
                self._known_match_ids = current_ids
                return
            new_ids = current_ids - self._known_match_ids
            if new_ids:
                print(f"[{COG_NAME}] Poll: {len(new_ids)} new match(es) detected — refreshing.")
                self._known_match_ids = current_ids
                await self._post_or_refresh(channel)
        except Exception as e:
            print(f"[{COG_NAME}] Poll loop error: {e}")

    @_poll_loop.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    # ── commands ──────────────────────────────────────────────

    @app_commands.command(
        name="setstandingschannel",
        description="[Admin] Set this channel as the live standings board channel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setstandingschannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.config["standings_channel_id"] = interaction.channel_id
        utils.save_config(self.bot.config)
        self._standings_message_id = None
        await interaction.followup.send(
            f"✅ Standings channel set to <#{interaction.channel_id}>.\n"
            f"Use `/refreshstandings` to post the first image.",
            ephemeral=True,
        )
        print(f"[{COG_NAME}] Standings channel → {interaction.channel_id}")

    @app_commands.command(
        name="refreshstandings",
        description="[Admin] Force-post an updated standings image now.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def refreshstandings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = self._get_standings_channel()
        if not channel:
            return await interaction.followup.send(
                "❌ No standings channel set. Run `/setstandingschannel` first.",
                ephemeral=True,
            )
        await interaction.followup.send("🔄 Refreshing standings...", ephemeral=True)
        try:
            await self._post_or_refresh(channel)
            await interaction.edit_original_response(
                content=f"✅ Standings posted to <#{channel.id}>."
            )
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error: {e}")
            print(f"[{COG_NAME}] Manual refresh error: {e}")

    @app_commands.command(
        name="standingspreview",
        description="Preview the current standings (only visible to you).",
    )
    async def standingspreview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        img_file = await self._build_image_file()
        if not img_file:
            return await interaction.followup.send(
                "⚠️ No standings data yet. Run `/updateresults` first.",
                ephemeral=True,
            )
        await interaction.followup.send(
            content="🏒 **Current OS4 League Standings**",
            file=img_file,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StandingsBoard(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
