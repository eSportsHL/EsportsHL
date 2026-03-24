import discord
from discord.ext import commands
from discord import app_commands
import utils
import asyncio

# ============================================================
# stats.py
# Version: 2.0.0
# Changelog:
#   v2.0.0 - BUGFIX: Removed broken /standings command that tried
#             to read a "Standings" worksheet that no longer exists.
#             standings.py now owns standings generation via the
#             Game Results tab. /standings now delegates to
#             StandingsBoard.trigger_refresh() or shows a preview
#             via the same logic. All blocking sheet calls wrapped
#             in run_in_executor for safety.
#   v1.0.0 - Initial release.
# ============================================================

VERSION  = "2.0.0"
COG_NAME = "Stats"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading")


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── AUTOCOMPLETE ──────────────────────────────────────────

    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        teams = self.bot.config.get("team_ids", {})
        choices = []
        for tid, name in teams.items():
            if current.lower() in name.lower() or current in str(tid):
                choices.append(app_commands.Choice(name=f"{name} ({tid})", value=str(tid)))
        return choices[:25]

    # ── /card ─────────────────────────────────────────────────

    @app_commands.command(name="card", description="View a detailed visual player card.")
    async def card(self, interaction: discord.Interaction, player_name: str):
        await interaction.response.defer()
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, utils.get_detailed_stats, player_name)
        logs  = utils.get_player_game_log(player_name, self.bot.config)
        img   = await loop.run_in_executor(
            None, utils.generate_player_card, player_name, stats, logs, "Player"
        )
        await interaction.followup.send(file=discord.File(img, "card.png"))

    # ── /team_card ────────────────────────────────────────────

    @app_commands.command(name="team_card", description="View detailed visual team stats.")
    @app_commands.autocomplete(team_id=team_autocomplete)
    async def team_card(self, interaction: discord.Interaction, team_id: str):
        await interaction.response.defer()
        loop  = asyncio.get_event_loop()
        tname = self.bot.config["team_ids"].get(team_id, team_id)

        all_stats   = await loop.run_in_executor(
            None, utils.get_season_stats_from_sheet, self.bot.config
        )
        all_rosters = await loop.run_in_executor(
            None, utils.get_roster_data_from_sheet, self.bot.config
        )
        # New schema keys by team name; fall back to team_id for old schema
        roster_names = all_rosters.get(tname, all_rosters.get(team_id, {}))
        roster_stats = [
            (name, all_stats[name]) for name in roster_names if name in all_stats
        ]

        img = await loop.run_in_executor(
            None, utils.generate_wide_team_card, tname, roster_stats
        )
        await interaction.followup.send(file=discord.File(img, "team_stats.png"))

    # ── /rosters ──────────────────────────────────────────────

    @app_commands.command(name="rosters", description="View team rosters and games played.")
    async def rosters(self, interaction: discord.Interaction):
        await interaction.response.defer()
        loop    = asyncio.get_event_loop()
        rosters = await loop.run_in_executor(
            None, utils.get_roster_data_from_sheet, self.bot.config
        )
        img = await loop.run_in_executor(
            None, utils.generate_roster_image, rosters, self.bot.config
        )
        await interaction.followup.send(file=discord.File(img, "rosters.png"))

    # ── /leagueleaders ────────────────────────────────────────

    @app_commands.command(name="leagueleaders", description="View league leaderboards.")
    async def leagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer()
        loop  = asyncio.get_event_loop()
        stats = await loop.run_in_executor(
            None, utils.get_season_stats_from_sheet, self.bot.config
        )
        img = await loop.run_in_executor(None, utils.generate_leaderboard_image, stats)
        await interaction.followup.send(file=discord.File(img, "leaders.png"))

    # ── /standings ────────────────────────────────────────────
    # Removed broken implementation that read a non-existent "Standings" worksheet.
    # Use /standingspreview (standings.py) for an ephemeral preview, or
    # /refreshstandings (standings.py) to post the live standings image.
    # The StandingsBoard cog auto-refreshes standings whenever new games appear.


async def setup(bot):
    await bot.add_cog(Stats(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
