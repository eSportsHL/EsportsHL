# ============================================================
#  Echelon League Bot — team_menu.py
#  Version: 1.0.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Posts a persistent team select menu to a configured channel.
#  Selecting a team shows that team's card (ephemeral).
#  Menu survives bot restarts — re-registered via setup_hook
#  and reposted if the message was deleted.
#
#  Commands:
#    /setteamchannel  — set the channel for the menu
#    /postteammenu    — (re)post the menu to the channel
#
#  Changelog:
#    v1.0.0 - Initial release.
# ============================================================

VERSION  = "1.0.0"
COG_NAME = "TeamMenu"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Persistent team card menu")

import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import utils

# Persistent custom_id — must never change or buttons break on restart
MENU_CUSTOM_ID = "team_menu_select_v1"


# ════════════════════════════════════════════════════════════
#  TEAM SELECT  (persistent)
# ════════════════════════════════════════════════════════════

class TeamSelect(discord.ui.Select):
    def __init__(self, team_ids: dict):
        self._team_ids = team_ids  # {tid: tname}

        options = []
        for tid, tname in sorted(team_ids.items(), key=lambda x: x[1]):
            options.append(discord.SelectOption(
                label=tname[:100],
                value=str(tid),
                description=f"View {tname[:50]} team card"
            ))

        # Discord limits selects to 25 options
        options = options[:25]

        super().__init__(
            custom_id=MENU_CUSTOM_ID,
            placeholder="🏒 Select a team to view their card...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        tid   = self.values[0]
        tname = self._team_ids.get(tid, tid)

        try:
            loop         = asyncio.get_event_loop()
            all_stats    = await loop.run_in_executor(
                None, utils.get_season_stats_from_sheet, interaction.client.config)
            roster_names = await loop.run_in_executor(
                None, utils.get_roster_data_from_sheet, interaction.client.config)

            roster_for_team = roster_names.get(tname, roster_names.get(str(tid), {}))
            roster_stats    = [
                (name, all_stats[name])
                for name in roster_for_team
                if name in all_stats
            ]

            buf = await loop.run_in_executor(
                None, utils.generate_wide_team_card, tname, roster_stats)

            await interaction.followup.send(
                file=discord.File(buf, filename=f"{tname}_card.png"),
                ephemeral=True
            )

        except Exception as e:
            print(f"[{COG_NAME}] Team card error for {tname}: {e}")
            await interaction.followup.send(
                f"❌ Could not generate team card for **{tname}**.\n`{e}`",
                ephemeral=True
            )


class TeamMenuView(discord.ui.View):
    def __init__(self, team_ids: dict):
        super().__init__(timeout=None)   # persistent — never times out
        self.add_item(TeamSelect(team_ids))


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class TeamMenu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print(f"✅ [{COG_NAME}] v{VERSION} initialized")

    async def cog_load(self):
        """
        Re-register the persistent view as early as possible so
        any existing menu message is immediately interactive.
        Then verify the message still exists and repost if needed.
        """
        team_ids = self.bot.config.get("team_ids", {})
        if team_ids:
            self.bot.add_view(TeamMenuView(team_ids))
            print(f"  ✔ [{COG_NAME}] Persistent TeamMenuView registered ({len(team_ids)} teams)")

        # Verify + repost happens after bot is ready
        self.bot.loop.create_task(self._ensure_menu_exists())

    async def _ensure_menu_exists(self):
        """Wait until ready then check the menu message still exists."""
        await self.bot.wait_until_ready()

        cid = self.bot.config.get("team_menu_channel_id")
        mid = self.bot.config.get("team_menu_message_id")
        if not cid:
            return  # not configured yet

        channel = self.bot.get_channel(int(cid))
        if not channel:
            print(f"[{COG_NAME}] Menu channel {cid} not found.")
            return

        # Try to fetch existing message
        if mid:
            try:
                await channel.fetch_message(int(mid))
                print(f"  ✔ [{COG_NAME}] Menu message verified (msg {mid})")
                return   # still there — nothing to do
            except (discord.NotFound, discord.HTTPException):
                print(f"[{COG_NAME}] Menu message gone — reposting.")

        # Repost
        await self._post_menu(channel)

    async def _post_menu(self, channel: discord.TextChannel):
        """Post the team menu to the channel and save the message ID."""
        team_ids = self.bot.config.get("team_ids", {})
        if not team_ids:
            print(f"[{COG_NAME}] No teams in config — menu not posted.")
            return

        try:
            league = utils.get_league_name() if hasattr(utils, "get_league_name") \
                     else self.bot.config.get("league_name", "League")
            bot_name = utils.get_bot_name() if hasattr(utils, "get_bot_name") \
                       else self.bot.config.get("bot_name", "Stats Bot")

            embed = discord.Embed(
                title=f"🏒 {league} — Team Cards",
                description=(
                    "Select a team from the menu below to view their\n"
                    "full roster stats, season record, and match history.\n\n"
                    f"*{len(team_ids)} teams available*"
                ),
                color=discord.Color.from_str("#58a6ff")
            )
            embed.set_footer(text=f"{bot_name} v{VERSION} • Updates automatically")

            view = TeamMenuView(team_ids)
            msg  = await channel.send(embed=embed, view=view)

            self.bot.config["team_menu_message_id"] = str(msg.id)
            utils.save_config(self.bot.config)
            print(f"  ✔ [{COG_NAME}] Menu posted (msg {msg.id}) in #{channel.name}")

        except Exception as e:
            print(f"[{COG_NAME}] Failed to post menu: {e}")

    # ── /setteamchannel ───────────────────────────────────────
    @app_commands.command(
        name="setteamchannel",
        description="Set the channel where the persistent team card menu is posted"
    )
    @app_commands.default_permissions(administrator=True)
    async def setteamchannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        self.bot.config["team_menu_channel_id"] = str(interaction.channel_id)
        self.bot.config.pop("team_menu_message_id", None)
        utils.save_config(self.bot.config)

        await interaction.followup.send(
            f"✅ Team menu channel set to <#{interaction.channel_id}>.\n"
            f"Run `/postteammenu` to post the menu here.",
            ephemeral=True
        )

    # ── /postteammenu ─────────────────────────────────────────
    @app_commands.command(
        name="postteammenu",
        description="Post (or repost) the team card select menu to the configured channel"
    )
    @app_commands.default_permissions(administrator=True)
    async def postteammenu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        cid = self.bot.config.get("team_menu_channel_id")
        if not cid:
            await interaction.followup.send(
                "❌ No team channel set. Run `/setteamchannel` first in the target channel.",
                ephemeral=True
            )
            return

        channel = self.bot.get_channel(int(cid))
        if not channel:
            await interaction.followup.send(
                f"❌ Could not find channel `{cid}`.", ephemeral=True)
            return

        # Delete old menu message if it exists
        old_mid = self.bot.config.get("team_menu_message_id")
        if old_mid:
            try:
                old_msg = await channel.fetch_message(int(old_mid))
                await old_msg.delete()
            except Exception:
                pass

        await self._post_menu(channel)
        await interaction.followup.send(
            f"✅ Team menu posted to <#{cid}>.", ephemeral=True)


# ════════════════════════════════════════════════════════════
#  SETUP
# ════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(TeamMenu(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
