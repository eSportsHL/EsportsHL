import discord
from discord.ext import commands
import utils

# ============================================================
# admin.py
# Version: 1.1.0
# Changelog:
#   v1.1.0 - BUGFIX: Removed !update_standings from help embed.
#             That command was never implemented and was replaced
#             by the standings.py cog (/refreshstandings,
#             /standingspreview, /updateresults). Updated help to
#             reflect the correct current command surface.
#   v1.0.0 - Initial release. !dashboard, !addteam, !removeteam,
#             !setchannel.
# ============================================================

VERSION  = "1.1.0"
COG_NAME = "Admin"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading")


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="dashboard", aliases=["status", "admin"])
    @commands.has_permissions(administrator=True)
    async def dashboard(self, ctx):
        """Displays the Admin Dashboard with current Bot config."""
        embed = discord.Embed(title="⚙️ Bot Admin Dashboard", color=discord.Color.dark_theme())

        teams     = self.bot.config.get("team_ids", {})
        team_list = "\n".join([f"**{name}** (ID: `{tid}`)" for tid, name in teams.items()])
        if not team_list:
            team_list = "None configured."
        embed.add_field(name="Tracked Teams (Auto-Scanner)", value=team_list, inline=False)

        ann_id  = self.bot.config.get("announcement_channel_id", 0)
        log_id  = self.bot.config.get("logging_channel_id", 0)
        ann_chan = f"<#{ann_id}>" if ann_id else "Not Set"
        log_chan = f"<#{log_id}>" if log_id else "Not Set"
        embed.add_field(
            name="Active Channels",
            value=f"📢 Announcements: {ann_chan}\n📝 Logging: {log_chan}",
            inline=False
        )

        plat  = self.bot.config.get("platform", "Unknown")
        sheet = self.bot.config.get("google_sheet_name", "Stats Sheet")
        embed.add_field(
            name="System Info",
            value=f"Platform Target: `{plat}`\nConnected Sheet: `{sheet}`",
            inline=False
        )

        await ctx.send(embed=embed)

    @commands.command(name="commands", aliases=["adminhelp", "setup"])
    async def admin_help(self, ctx):
        """Displays the Admin Help Menu."""
        embed = discord.Embed(title="🛠️ Bot Admin Commands", color=discord.Color.gold())
        embed.description = "Use these commands to configure the bot."

        # ── Prefix commands ───────────────────────────────────
        embed.add_field(name="!dashboard", value="View the current active configuration.", inline=False)
        embed.add_field(
            name="!setchannel [type]",
            value="Sets the active channel.\nUsage: `!setchannel announcement` or `!setchannel logging`",
            inline=False
        )
        embed.add_field(
            name="!addteam [ID] [Name]",
            value="Adds a team to the auto-scan list.\nUsage: `!addteam 123456 MyClub`",
            inline=False
        )
        embed.add_field(
            name="!removeteam [ID]",
            value="Removes a team from the list.\nUsage: `!removeteam 123456`",
            inline=False
        )

        # ── Slash commands — standings ─────────────────────────
        embed.add_field(
            name="/refreshstandings",
            value="Post an updated standings image to the standings channel now.",
            inline=False
        )
        embed.add_field(
            name="/standingspreview",
            value="Preview the current standings (ephemeral — only you see it).",
            inline=False
        )
        embed.add_field(
            name="/setstandingschannel",
            value="Set the current channel as the live standings board.",
            inline=False
        )

        # ── Slash commands — results ───────────────────────────
        embed.add_field(
            name="/updateresults",
            value="Rebuild the Game Results sheet tab and refresh the season summary image.",
            inline=False
        )
        embed.add_field(
            name="/refreshresults",
            value="Force-repost ALL result pages (use after a merge/unmerge).",
            inline=False
        )

        # ── Slash commands — auto images ───────────────────────
        embed.add_field(
            name="/autorefresh",
            value="Force an immediate refresh of all auto-image channels.",
            inline=False
        )

        embed.set_footer(text="Only Administrators can use these commands.")
        await ctx.send(embed=embed)

    @commands.command(name="addteam")
    @commands.has_permissions(administrator=True)
    async def add_team(self, ctx, team_id: str, *, team_name: str):
        self.bot.config["team_ids"][str(team_id).strip()] = team_name
        utils.save_config(self.bot.config)
        await utils.send_log(self.bot, f"✅ Team Added: {team_name} ({team_id})")
        await ctx.send(f"✅ Added Team: **{team_name}**")

    @commands.command(name="removeteam")
    @commands.has_permissions(administrator=True)
    async def remove_team(self, ctx, team_id: str):
        if team_id in self.bot.config["team_ids"]:
            name = self.bot.config["team_ids"][team_id]
            del self.bot.config["team_ids"][team_id]
            utils.save_config(self.bot.config)
            await utils.send_log(self.bot, f"🗑️ Team Removed: {name} ({team_id})")
            await ctx.send(f"🗑️ Removed Team ID: {team_id}")
        else:
            await ctx.send("❌ Team ID not found.")

    @commands.command(name="setchannel")
    @commands.has_permissions(administrator=True)
    async def set_channel(self, ctx, channel_type: str):
        ctype = channel_type.lower()
        if ctype in ["announcement", "logging"]:
            key = f"{ctype}_channel_id"
            self.bot.config[key] = ctx.channel.id
            utils.save_config(self.bot.config)
            msg = f"✅ **{ctype.capitalize()} Channel** set to {ctx.channel.mention}"
            await ctx.send(msg)
            if ctype == "logging":
                await utils.send_log(self.bot, "📝 Logging system initialized.")
        else:
            await ctx.send("❌ Usage: `!setchannel announcement` or `!setchannel logging`")


async def setup(bot):
    await bot.add_cog(Admin(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
