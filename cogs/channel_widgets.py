# ============================================================
#  Echelon League Bot — channel_widgets.py
#  Version: 1.0.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Provides three persistent interactive widgets that can be
#  posted to any channel. All views survive bot restarts.
#
#  ┌─────────────────────────────────────────────────────────┐
#  │ WIDGET 1 — Team Card Selector                           │
#  │   Dropdown of all configured teams.                     │
#  │   Selecting a team → ephemeral team card image.         │
#  │   Commands: /postteamwidget                             │
#  │   Use in: #team-cards, #standings, #rosters, anywhere  │
#  ├─────────────────────────────────────────────────────────┤
#  │ WIDGET 2 — Stats Explorer (Leaders channel)             │
#  │   Dropdown of ALL stat categories (not just the ones    │
#  │   shown on the auto-posted leaderboard image).          │
#  │   Selecting a category → ephemeral top-10 embed.        │
#  │   Commands: /postleaderswidget                          │
#  ├─────────────────────────────────────────────────────────┤
#  │ WIDGET 3 — Game Browser (Results channel)               │
#  │   "Browse Games" button → live game selector (same UX   │
#  │   as /gameresults). Always fetches fresh game list.     │
#  │   Commands: /postgamewidget                             │
#  └─────────────────────────────────────────────────────────┘
#
#  All widgets track their message IDs in config.json and
#  auto-repost if the message was deleted.
#
#  Changelog:
#    v1.0.0 - Initial release.
# ============================================================

VERSION  = "1.0.0"
COG_NAME = "ChannelWidgets"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Team / Leaders / Game widgets")

import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import utils

# ════════════════════════════════════════════════════════════
#  CONFIG KEYS  (stored in config.json)
# ════════════════════════════════════════════════════════════

# Each widget can be posted to any number of channels.
# We store a list of {channel_id, message_id} dicts per widget type.
_KEY_TEAM_WIDGETS    = "widget_team_posts"    # list of {"cid": ..., "mid": ...}
_KEY_LEADERS_WIDGETS = "widget_leaders_posts"
_KEY_GAMES_WIDGETS   = "widget_games_posts"

# ════════════════════════════════════════════════════════════
#  ALL STAT CATEGORIES  (used by Leaders Explorer)
# ════════════════════════════════════════════════════════════
#  key         = key in the season_stats dict (from statsreader.py)
#  label       = human-readable display name
#  pos         = "Skater" | "Goalie"
#  fmt         = "int" | "pct" | "sv_pct"
#  min_gp      = minimum GP to appear (0 = all)

ALL_CATEGORIES = [
    # ── Skaters ──────────────────────────────────────────────
    ("P",         "Points",              "Skater", "int",    1),
    ("G",         "Goals",               "Skater", "int",    1),
    ("A",         "Assists",             "Skater", "int",    1),
    ("+/-",       "Plus / Minus",        "Skater", "int",    1),
    ("Hits",      "Hits",                "Skater", "int",    1),
    ("S",         "Shots",               "Skater", "int",    1),
    ("PIM",       "Penalties (PIM)",     "Skater", "int",    1),
    ("TK",        "Takeaways",           "Skater", "int",    1),
    ("GV",        "Giveaways",           "Skater", "int",    1),
    ("INT",       "Interceptions",       "Skater", "int",    1),
    ("BS",        "Blocked Shots",       "Skater", "int",    1),
    ("GWG",       "Game-Winning Goals",  "Skater", "int",    1),
    ("PPG",       "Power Play Goals",    "Skater", "int",    1),
    ("SHG",       "Short-Hand Goals",    "Skater", "int",    1),
    ("FO%",       "Faceoff %",           "Skater", "pct",    3),
    ("Pass%",     "Pass %",              "Skater", "pct",    3),
    ("ShotAtt",   "Shot Attempts",       "Skater", "int",    1),
    ("Sauc",      "Saucer Passes",       "Skater", "int",    1),
    ("DEF",       "Deflections",         "Skater", "int",    1),
    ("PD",        "Penalties Drawn",     "Skater", "int",    1),
    # ── Goalies ──────────────────────────────────────────────
    ("Save % Value", "Save %",           "Goalie", "sv_pct", 3),
    ("Sv",           "Saves",            "Goalie", "int",    1),
    ("GA",           "Goals Against",    "Goalie", "int",    1),
    ("DS",           "Desperate Saves",  "Goalie", "int",    1),
]

# Medal emojis for top 3
_MEDALS = ["🥇", "🥈", "🥉"]
_ACCENT_COLOR = discord.Color.from_str("#C9A84C")


def _fmt_val(val, fmt: str) -> str:
    if fmt == "sv_pct":
        try:    return f"{float(val):.3f}"
        except: return "-.---"
    if fmt == "pct":
        try:    return f"{float(val):.1f}%"
        except: return "-.--%"
    try:    return str(int(float(val)))
    except: return "0"


def _get_league_name() -> str:
    try:    return utils.get_league_name()
    except: return utils.load_config().get("league_name", "League")


# ════════════════════════════════════════════════════════════
#  WIDGET 1 — TEAM CARD SELECTOR
# ════════════════════════════════════════════════════════════

class TeamWidgetSelect(discord.ui.Select):
    def __init__(self, team_ids: dict):
        self._team_ids = team_ids
        options = [
            discord.SelectOption(
                label=tname[:100],
                value=str(tid),
                description=f"View {tname[:50]} team card",
                emoji="🏒"
            )
            for tid, tname in sorted(team_ids.items(), key=lambda x: x[1])
        ][:25]
        super().__init__(
            custom_id="widget_team_select_v1",
            placeholder="🏒 Select a team to view their card...",
            min_values=1, max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tid   = self.values[0]
        tname = self._team_ids.get(tid, tid)

        try:
            loop         = asyncio.get_event_loop()
            all_stats    = await loop.run_in_executor(
                None, utils.get_season_stats_from_sheet, interaction.client.config
            )
            all_rosters  = await loop.run_in_executor(
                None, utils.get_roster_data_from_sheet, interaction.client.config
            )
            roster_names = all_rosters.get(tname, all_rosters.get(str(tid), {}))
            roster_stats = [
                (name, all_stats[name])
                for name in roster_names
                if name in all_stats
            ]
            if not roster_stats:
                return await interaction.followup.send(
                    f"⚠️ No stats found for **{tname}** yet.", ephemeral=True
                )
            buf = await loop.run_in_executor(
                None, utils.generate_wide_team_card, tname, roster_stats
            )
            await interaction.followup.send(
                file=discord.File(buf, filename=f"{tname}_card.png"),
                ephemeral=True
            )
        except Exception as e:
            print(f"[{COG_NAME}] Team card error ({tname}): {e}")
            await interaction.followup.send(
                f"❌ Could not generate team card for **{tname}**.\n`{e}`", ephemeral=True
            )


class TeamWidgetView(discord.ui.View):
    def __init__(self, team_ids: dict):
        super().__init__(timeout=None)
        if team_ids:
            self.add_item(TeamWidgetSelect(team_ids))


# ════════════════════════════════════════════════════════════
#  WIDGET 2 — STATS EXPLORER  (all categories)
# ════════════════════════════════════════════════════════════

class LeadersWidgetSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{label} ({pos[0]})",   # e.g. "Points (S)"
                description=f"{'Skater' if pos == 'Skater' else 'Goalie'} leaderboard — Top 10",
                value=key,
                emoji="📊" if pos == "Skater" else "🥅"
            )
            for key, label, pos, fmt, min_gp in ALL_CATEGORIES
        ]
        super().__init__(
            custom_id="widget_leaders_select_v1",
            placeholder="📊 Choose a stat category to explore...",
            min_values=1, max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        selected_key = self.values[0]
        cat = next((c for c in ALL_CATEGORIES if c[0] == selected_key), None)
        if not cat:
            return await interaction.followup.send("❌ Category not found.", ephemeral=True)

        key, label, pos, fmt, min_gp = cat

        try:
            loop         = asyncio.get_event_loop()
            season_stats = await loop.run_in_executor(
                None, utils.get_season_stats_from_sheet, interaction.client.config
            )
        except Exception as e:
            return await interaction.followup.send(f"❌ Sheet error: `{e}`", ephemeral=True)

        # Filter by position and min_gp, sort by value
        players = [
            (name, s)
            for name, s in season_stats.items()
            if s.get("Main Position") == pos and s.get("GP", 0) >= min_gp
        ]
        # For giveaways, lower is better — invert sort
        reverse = key != "GV"
        players.sort(key=lambda x: x[1].get(key, 0), reverse=reverse)

        league = _get_league_name().upper()
        pos_label = "SKATERS" if pos == "Skater" else "GOALIES"

        lines = []
        for rank, (pname, pstats) in enumerate(players[:10], 1):
            val    = pstats.get(key, 0)
            v_str  = _fmt_val(val, fmt)
            gp     = pstats.get("GP", 0)
            team   = pstats.get("Team", "")
            medal  = _MEDALS[rank - 1] if rank <= 3 else f"`{rank}.`"
            t_str  = f" • {team}" if team else ""
            lines.append(f"{medal}  **{pname}**{t_str} — **{v_str}**  *(GP: {gp})*")

        if not lines:
            lines = ["*No qualifying players found.*"]

        embed = discord.Embed(
            title=f"🏆  {league} — {label.upper()} LEADERS",
            description="\n".join(lines),
            color=_ACCENT_COLOR
        )
        embed.set_footer(
            text=f"{pos_label}  •  Min {min_gp} GP required  •  {_get_league_name()} Stats Explorer v{VERSION}"
        )
        if min_gp > 1:
            embed.add_field(
                name="ℹ️ Filter",
                value=f"Only players with **{min_gp}+ GP** are shown for {label}.",
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


class LeadersWidgetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LeadersWidgetSelect())


# ════════════════════════════════════════════════════════════
#  WIDGET 3 — GAME BROWSER  (same UX as /gameresults)
# ════════════════════════════════════════════════════════════

class GamesWidgetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎮  Browse Game Results",
        style=discord.ButtonStyle.primary,
        custom_id="widget_games_browse_v1"
    )
    async def browse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        loop = asyncio.get_event_loop()
        sh   = await loop.run_in_executor(None, utils.get_sheet)
        if not sh:
            return await interaction.followup.send("❌ Sheet connection failed.", ephemeral=True)

        try:
            # Deferred import — game_results is loaded by the time any user
            # clicks this button (all cogs load before on_ready fires).
            from cogs.game_results import _build_game_rows, GameSelectView, _get_league_name
        except Exception as e:
            return await interaction.followup.send(f"❌ Could not load game data: `{e}`", ephemeral=True)

        summary, team_names = await loop.run_in_executor(
            None, _build_game_rows, sh, interaction.client.config
        )
        if not summary:
            return await interaction.followup.send(
                "⚠️ No game data found. Run `/updateresults` first.", ephemeral=True
            )

        reg = sum(1 for g in summary if g["game_type"] == "REG")
        ot  = sum(1 for g in summary if g["game_type"] == "OT")
        dnf = sum(1 for g in summary if g["game_type"] == "DNF")

        embed = discord.Embed(
            title=f"🏒 {_get_league_name()} — Game Results",
            description=(
                f"**{len(summary)}** games this season.\n"
                f"🟩 Regulation: `{reg}`  |  🟨 OT: `{ot}`  |  🟧 DNF: `{dnf}`\n\n"
                "Select a game below for scoreboard image + per-player stats."
            ),
            color=_ACCENT_COLOR
        )
        embed.set_footer(text=f"{_get_league_name()} • ChannelWidgets v{VERSION}")

        await interaction.followup.send(
            embed=embed,
            view=GameSelectView(summary, team_names),
            ephemeral=True
        )


# ════════════════════════════════════════════════════════════
#  HELPERS — post / verify / re-register
# ════════════════════════════════════════════════════════════

async def _verify_or_repost(bot, config_key: str, make_embed_fn, make_view_fn):
    """
    Check every stored post for this widget type.
    Re-post to any channel where the message was deleted.
    """
    posts = bot.config.get(config_key, [])
    updated = []
    for entry in posts:
        cid = entry.get("cid")
        mid = entry.get("mid")
        if not cid:
            continue
        channel = bot.get_channel(int(cid))
        if not channel:
            updated.append(entry)   # keep it; channel might be unavailable temporarily
            continue
        if mid:
            try:
                await channel.fetch_message(int(mid))
                updated.append(entry)   # message still there — keep
                continue
            except (discord.NotFound, discord.HTTPException):
                pass
        # Message missing — repost
        new_mid = await _do_post(channel, make_embed_fn(bot), make_view_fn(bot))
        if new_mid:
            updated.append({"cid": str(cid), "mid": str(new_mid)})
            print(f"[{COG_NAME}] Reposted widget to #{channel.name} (msg {new_mid})")

    bot.config[config_key] = updated
    utils.save_config(bot.config)


async def _do_post(channel: discord.TextChannel, embed: discord.Embed,
                   view: discord.ui.View) -> int | None:
    try:
        msg = await channel.send(embed=embed, view=view)
        return msg.id
    except Exception as e:
        print(f"[{COG_NAME}] Failed to post widget to #{channel.name}: {e}")
        return None


def _team_embed(bot) -> discord.Embed:
    league = _get_league_name()
    teams  = bot.config.get("team_ids", {})
    embed  = discord.Embed(
        title=f"🏒  {league} — Team Cards",
        description=(
            "Select a team from the menu below to view their full roster stats, "
            "season record, and match history.\n\n"
            f"*{len(teams)} teams available*"
        ),
        color=_ACCENT_COLOR
    )
    embed.set_footer(text=f"ChannelWidgets v{VERSION} • Updates automatically")
    return embed


def _team_view(bot) -> TeamWidgetView:
    return TeamWidgetView(bot.config.get("team_ids", {}))


def _leaders_embed(bot) -> discord.Embed:
    league = _get_league_name()
    cats_s = sum(1 for c in ALL_CATEGORIES if c[2] == "Skater")
    cats_g = sum(1 for c in ALL_CATEGORIES if c[2] == "Goalie")
    embed  = discord.Embed(
        title=f"📊  {league} — Stats Explorer",
        description=(
            "Select any stat category to see the **Top 10** league leaders.\n\n"
            f"**{cats_s} skater categories** and **{cats_g} goalie categories** available.\n"
            "*Results are ephemeral — only you see them.*"
        ),
        color=_ACCENT_COLOR
    )
    embed.set_footer(text=f"ChannelWidgets v{VERSION} • All categories shown")
    return embed


def _leaders_view(bot) -> LeadersWidgetView:
    return LeadersWidgetView()


def _games_embed(bot) -> discord.Embed:
    league = _get_league_name()
    embed  = discord.Embed(
        title=f"🎮  {league} — Game Browser",
        description=(
            "Click the button below to browse all game results this season.\n\n"
            "For each game you can view:\n"
            "• Full scoreboard image\n"
            "• Individual player stat cards\n\n"
            "*Always shows the latest data.*"
        ),
        color=_ACCENT_COLOR
    )
    embed.set_footer(text=f"ChannelWidgets v{VERSION} • Live game data")
    return embed


def _games_view(bot) -> GamesWidgetView:
    return GamesWidgetView()


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class ChannelWidgets(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print(f"✅ [{COG_NAME}] v{VERSION} initialized")

    async def cog_load(self):
        """
        Re-register all persistent views immediately (no wait_until_ready).
        Verification/repost tasks run after ready via create_task.
        """
        team_ids = self.bot.config.get("team_ids", {})
        if team_ids:
            self.bot.add_view(TeamWidgetView(team_ids))
            print(f"  ✔ [{COG_NAME}] TeamWidgetView registered ({len(team_ids)} teams)")

        self.bot.add_view(LeadersWidgetView())
        print(f"  ✔ [{COG_NAME}] LeadersWidgetView registered ({len(ALL_CATEGORIES)} categories)")

        self.bot.add_view(GamesWidgetView())
        print(f"  ✔ [{COG_NAME}] GamesWidgetView registered")

        self.bot.loop.create_task(self._verify_all_widgets())

    async def _verify_all_widgets(self):
        """Wait for ready, then verify all widget messages still exist."""
        await self.bot.wait_until_ready()
        await _verify_or_repost(self.bot, _KEY_TEAM_WIDGETS,    _team_embed,    _team_view)
        await _verify_or_repost(self.bot, _KEY_LEADERS_WIDGETS, _leaders_embed, _leaders_view)
        await _verify_or_repost(self.bot, _KEY_GAMES_WIDGETS,   _games_embed,   _games_view)
        print(f"[{COG_NAME}] Widget verification complete.")

    # ── /postteamwidget ───────────────────────────────────────

    @app_commands.command(
        name="postteamwidget",
        description="[Admin] Post a team card selector widget to this channel."
    )
    @app_commands.default_permissions(administrator=True)
    async def postteamwidget(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        team_ids = self.bot.config.get("team_ids", {})
        if not team_ids:
            return await interaction.followup.send(
                "❌ No teams configured. Use `!addteam` first.", ephemeral=True
            )
        view  = TeamWidgetView(team_ids)
        embed = _team_embed(self.bot)
        mid   = await _do_post(interaction.channel, embed, view)
        if mid:
            posts = self.bot.config.get(_KEY_TEAM_WIDGETS, [])
            posts.append({"cid": str(interaction.channel_id), "mid": str(mid)})
            self.bot.config[_KEY_TEAM_WIDGETS] = posts
            utils.save_config(self.bot.config)
            await interaction.followup.send(
                f"✅ Team card selector posted to <#{interaction.channel_id}>.", ephemeral=True
            )
            print(f"[{COG_NAME}] Team widget posted to #{interaction.channel.name} (msg {mid})")
        else:
            await interaction.followup.send("❌ Failed to post widget.", ephemeral=True)

    # ── /postleaderswidget ────────────────────────────────────

    @app_commands.command(
        name="postleaderswidget",
        description="[Admin] Post a full stats explorer dropdown to this channel."
    )
    @app_commands.default_permissions(administrator=True)
    async def postleaderswidget(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view  = LeadersWidgetView()
        embed = _leaders_embed(self.bot)
        mid   = await _do_post(interaction.channel, embed, view)
        if mid:
            posts = self.bot.config.get(_KEY_LEADERS_WIDGETS, [])
            posts.append({"cid": str(interaction.channel_id), "mid": str(mid)})
            self.bot.config[_KEY_LEADERS_WIDGETS] = posts
            utils.save_config(self.bot.config)
            await interaction.followup.send(
                f"✅ Stats explorer posted to <#{interaction.channel_id}>.", ephemeral=True
            )
            print(f"[{COG_NAME}] Leaders widget posted to #{interaction.channel.name} (msg {mid})")
        else:
            await interaction.followup.send("❌ Failed to post widget.", ephemeral=True)

    # ── /postgamewidget ───────────────────────────────────────

    @app_commands.command(
        name="postgamewidget",
        description="[Admin] Post a live game browser button to this channel."
    )
    @app_commands.default_permissions(administrator=True)
    async def postgamewidget(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view  = GamesWidgetView()
        embed = _games_embed(self.bot)
        mid   = await _do_post(interaction.channel, embed, view)
        if mid:
            posts = self.bot.config.get(_KEY_GAMES_WIDGETS, [])
            posts.append({"cid": str(interaction.channel_id), "mid": str(mid)})
            self.bot.config[_KEY_GAMES_WIDGETS] = posts
            utils.save_config(self.bot.config)
            await interaction.followup.send(
                f"✅ Game browser posted to <#{interaction.channel_id}>.", ephemeral=True
            )
            print(f"[{COG_NAME}] Games widget posted to #{interaction.channel.name} (msg {mid})")
        else:
            await interaction.followup.send("❌ Failed to post widget.", ephemeral=True)

    # ── /removewidgets ────────────────────────────────────────

    @app_commands.command(
        name="removewidgets",
        description="[Admin] Remove all tracked widget messages in this channel."
    )
    @app_commands.default_permissions(administrator=True)
    async def removewidgets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        removed = 0
        for key in (_KEY_TEAM_WIDGETS, _KEY_LEADERS_WIDGETS, _KEY_GAMES_WIDGETS):
            posts     = self.bot.config.get(key, [])
            remaining = []
            for entry in posts:
                if str(entry.get("cid")) != str(interaction.channel_id):
                    remaining.append(entry)
                    continue
                mid = entry.get("mid")
                if mid:
                    try:
                        m = await interaction.channel.fetch_message(int(mid))
                        await m.delete()
                        removed += 1
                    except Exception:
                        removed += 1  # count it even if already gone
            self.bot.config[key] = remaining

        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ Removed **{removed}** widget message(s) from this channel.", ephemeral=True
        )

    # ── /listwidgets ──────────────────────────────────────────

    @app_commands.command(
        name="listwidgets",
        description="[Admin] Show all active widget posts across all channels."
    )
    @app_commands.default_permissions(administrator=True)
    async def listwidgets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = []
        labels = {
            _KEY_TEAM_WIDGETS:    "🏒 Team Card Selector",
            _KEY_LEADERS_WIDGETS: "📊 Stats Explorer",
            _KEY_GAMES_WIDGETS:   "🎮 Game Browser",
        }
        for key, label in labels.items():
            posts = self.bot.config.get(key, [])
            if not posts:
                lines.append(f"**{label}** — no active posts")
                continue
            for entry in posts:
                lines.append(f"**{label}** → <#{entry['cid']}> (msg `{entry.get('mid','?')}`)")

        embed = discord.Embed(
            title="📋 Active Channel Widgets",
            description="\n".join(lines) or "No widgets posted.",
            color=_ACCENT_COLOR
        )
        embed.set_footer(text=f"ChannelWidgets v{VERSION}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── error handler ─────────────────────────────────────────

    @postteamwidget.error
    @postleaderswidget.error
    @postgamewidget.error
    @removewidgets.error
    @listwidgets.error
    async def _admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Error: `{error}`", ephemeral=True)


# ════════════════════════════════════════════════════════════
#  SETUP
# ════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelWidgets(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
