import discord
from discord.ext import commands
from discord import app_commands
import os
import json

# ══════════════════════════════════════════════════════════════════════════════
#  RK GRIZZLIES — AVAILABILITY COG
#  Version: 2.1.0  |  Fix: Persistent buttons survive restart
#                  |  New:  Admin schedule editor (add/remove days & times)
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "2.1.0"

# ── Branding ──────────────────────────────────────────────────────────────────
RK_GOLD         = discord.Color(0xC9A84C)
RK_LOGO_URL     = ""   # ← Paste your direct image URL here
RK_BANNER_TITLE = "🏒 💥 RK GRIZZLIES 💥🏒"
RK_FOOTER_ICON  = RK_LOGO_URL

# ══════════════════════════════════════════════════════════════════════════════
#  DATA FILES
# ══════════════════════════════════════════════════════════════════════════════

POLL_FILE     = "poll_data.json"
SCHEDULE_FILE = "schedule_data.json"   # persists admin edits to schedules

# ══════════════════════════════════════════════════════════════════════════════
#  DEFAULT SCHEDULES  (used only if schedule_data.json doesn't exist yet)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_SCHEDULES = {
    "RK": {
        "days": {
            "Thursday": "9:45 PM • 10:15 PM",
            "Friday":   "8:30 PM • 9:00 PM • 9:30 PM",
            "Saturday": "8:30 PM • 9:00 PM • 9:30 PM",
            "Sunday":   "9:45 PM • 10:15 PM",
        },
    },
    "ITHL": {
        "days": {
            "Thursday": "9 PM",
        },
    },
}

# Colors per league (not stored in JSON — kept in code)
LEAGUE_COLORS = {
    "RK":   RK_GOLD,
    "ITHL": discord.Color.blue(),
}

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

TEAM_CHANNELS = {
    "Team Grizzlies":   "grizzlies-availability",
    "Jasper Grizzlies": "grizz-avail",
}

# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def load_schedules() -> dict:
    """Load schedules from JSON, falling back to defaults."""
    if not os.path.exists(SCHEDULE_FILE):
        return {k: dict(v) for k, v in DEFAULT_SCHEDULES.items()}
    try:
        with open(SCHEDULE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {k: dict(v) for k, v in DEFAULT_SCHEDULES.items()}

def save_schedules(schedules: dict):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedules, f, indent=4)

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def resolve_names(uid_list: list, guild: discord.Guild) -> list[str]:
    names = []
    for uid in uid_list:
        member = guild.get_member(int(uid))
        names.append(member.display_name if member else f"<@{uid}>")
    return names


def _apply_rk_branding(embed: discord.Embed, league: str) -> discord.Embed:
    if RK_LOGO_URL:
        embed.set_thumbnail(url=RK_LOGO_URL)
    footer_kwargs = {"text": f"{RK_BANNER_TITLE}  •  {league} Availability  •  All times EST/EDT"}
    if RK_LOGO_URL:
        footer_kwargs["icon_url"] = RK_FOOTER_ICON
    embed.set_footer(**footer_kwargs)
    return embed


def build_summary_embed(instance: dict) -> discord.Embed:
    """Channel-visible summary — always at the bottom, shows available only."""
    league   = instance.get("league", "League")
    color    = discord.Color(instance["color"])
    schedule = instance.get("schedule", {})

    embed = discord.Embed(
        title=f"📋  {RK_BANNER_TITLE}  ·  {league} — Weekly Availability",
        color=color,
    )
    for day, avail_ids in instance["availability_data"].items():
        times     = schedule.get(day, "")
        count     = len(avail_ids)
        indicator = "🟢" if count else "⚪"
        mentions  = "  ".join(f"<@{uid}>" for uid in avail_ids) if avail_ids else "*No one yet*"
        embed.add_field(
            name=f"{indicator} {day} ({count} ✅)",
            value=f"⏰ {times}\n{mentions}",
            inline=True,
        )

    footer_kwargs = {"text": f'{RK_BANNER_TITLE}  •  Tap "📅 Mark My Availability" above to set your days ↑'}
    if RK_LOGO_URL:
        footer_kwargs["icon_url"] = RK_FOOTER_ICON
    embed.set_footer(**footer_kwargs)
    if RK_LOGO_URL:
        embed.set_thumbnail(url=RK_LOGO_URL)
    return embed


def build_weekly_panel(instance: dict, guild: discord.Guild, show_unavailable: bool = False) -> discord.Embed:
    """Ephemeral panel embed — toggles between available and unavailable views."""
    league   = instance.get("league", "League")
    color    = discord.Color(instance["color"])
    schedule = instance.get("schedule", {})

    if show_unavailable:
        embed = discord.Embed(
            title=f"📅  {RK_BANNER_TITLE}  ·  {league} — Who's Unavailable",
            description="Players who marked ❌ for each day.",
            color=discord.Color.red(),
        )
        for day in instance["availability_data"]:
            unavail_ids = instance.get("unavailable_data", {}).get(day, [])
            times       = schedule.get(day, "")
            names       = resolve_names(unavail_ids, guild)
            player_str  = ", ".join(names) if names else "*No one marked unavailable*"
            embed.add_field(
                name=f"🗓️ {day}  |  ⏰ {times}",
                value=f"❌ {player_str}",
                inline=False,
            )
    else:
        embed = discord.Embed(
            title=f"📅  {RK_BANNER_TITLE}  ·  {league} — Mark Your Availability",
            description="Tap ✅ or ❌ for each day. Changes save instantly.",
            color=color,
        )
        for day, avail_ids in instance["availability_data"].items():
            times      = schedule.get(day, "")
            names      = resolve_names(avail_ids, guild)
            player_str = ", ".join(names) if names else "*No one yet*"
            embed.add_field(
                name=f"🗓️ {day}  |  ⏰ {times}",
                value=f"✅ {player_str}",
                inline=False,
            )

    footer_kwargs = {"text": f"{RK_BANNER_TITLE}  •  Only you can see this panel."}
    if RK_LOGO_URL:
        footer_kwargs["icon_url"] = RK_FOOTER_ICON
    embed.set_footer(**footer_kwargs)
    if RK_LOGO_URL:
        embed.set_thumbnail(url=RK_LOGO_URL)
    return embed


# ══════════════════════════════════════════════════════════════════════════════
#  DAY TOGGLE BUTTONS
# ══════════════════════════════════════════════════════════════════════════════

class DayToggleButton(discord.ui.Button):
    def __init__(self, day: str, row: int):
        super().__init__(
            label=f"✅ {day}",
            style=discord.ButtonStyle.success,
            custom_id=f"toggle_{day}",
            row=row,
        )
        self.day = day

    def _sync_style(self, uid: str, instance: dict):
        if uid in instance["availability_data"].get(self.day, []):
            self.label = f"✅ {self.day}"
            self.style = discord.ButtonStyle.success
        elif uid in instance.get("unavailable_data", {}).get(self.day, []):
            self.label = f"❌ {self.day}"
            self.style = discord.ButtonStyle.danger
        else:
            self.label = f"— {self.day}"
            self.style = discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        cog: "Availability" = interaction.client.cogs.get("Availability")
        ch_str = str(interaction.channel_id)
        if not cog or ch_str not in cog.active_poll_instances:
            await interaction.response.send_message("Poll not found.", ephemeral=True)
            return

        instance = cog.active_poll_instances[ch_str]
        uid      = str(interaction.user.id)

        avail   = instance["availability_data"][self.day]
        unavail = instance.setdefault("unavailable_data", {}).setdefault(self.day, [])

        if uid in avail:
            avail.remove(uid)
            if uid not in unavail:
                unavail.append(uid)
        elif uid in unavail:
            unavail.remove(uid)
            if uid not in avail:
                avail.append(uid)
        else:
            avail.append(uid)

        cog.save_data()

        for item in self.view.children:
            if isinstance(item, DayToggleButton):
                item._sync_style(uid, instance)

        updated_embed = build_weekly_panel(
            instance, interaction.guild, show_unavailable=self.view.show_unavailable
        )
        await interaction.response.edit_message(embed=updated_embed, view=self.view)
        await cog.refresh_summary(interaction.channel, instance)


# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY PANEL VIEW
# ══════════════════════════════════════════════════════════════════════════════

class WeeklyPanelView(discord.ui.View):
    def __init__(self, instance: dict, uid: str):
        super().__init__(timeout=300)
        self.instance         = instance
        self.uid              = uid
        self.show_unavailable = False

        days = list(instance["availability_data"].keys())
        for i, day in enumerate(days):
            btn = DayToggleButton(day, row=i // 5)
            btn._sync_style(uid, instance)
            self.add_item(btn)

        last_row = (len(days) - 1) // 5 + 1
        toggle = discord.ui.Button(
            label="👁  Show Unavailable",
            style=discord.ButtonStyle.secondary,
            custom_id="toggle_unavail_view",
            row=min(last_row, 4),
        )
        toggle.callback = self.toggle_unavailable_view
        self.unavail_btn = toggle
        self.add_item(toggle)

    async def toggle_unavailable_view(self, interaction: discord.Interaction):
        self.show_unavailable = not self.show_unavailable
        self.unavail_btn.label = (
            "✅  Show Available" if self.show_unavailable else "👁  Show Unavailable"
        )
        self.unavail_btn.style = (
            discord.ButtonStyle.success if self.show_unavailable else discord.ButtonStyle.secondary
        )
        embed = build_weekly_panel(self.instance, interaction.guild, self.show_unavailable)
        await interaction.response.edit_message(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN POLL VIEW
#  timeout=None + stable custom_id = survives bot restarts
#  Re-registered on boot via bot.add_view(AvailabilityView()) in __init__
# ══════════════════════════════════════════════════════════════════════════════

class AvailabilityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📅  Mark My Availability",
        style=discord.ButtonStyle.primary,
        custom_id="open_weekly_panel",
        row=0,
    )
    async def open_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Availability" = interaction.client.cogs.get("Availability")
        ch_str = str(interaction.channel_id)

        if not cog or ch_str not in cog.active_poll_instances:
            await interaction.response.send_message(
                "Poll not found — ask an admin to repost it.", ephemeral=True
            )
            return

        instance = cog.active_poll_instances[ch_str]
        uid      = str(interaction.user.id)

        embed = build_weekly_panel(instance, interaction.guild)
        view  = WeeklyPanelView(instance, uid)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
#  COG
# ══════════════════════════════════════════════════════════════════════════════

class Availability(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot       = bot
        self.schedules = load_schedules()
        self.active_poll_instances: dict = self._load_poll_data()

        # ── KEY FIX: re-register the persistent view on every boot ────────────
        # Without this, Discord.py forgets about old buttons after restart.
        # This call doesn't need the original message — it just tells the bot
        # "route any interaction with custom_id='open_weekly_panel' to this view."
        bot.add_view(AvailabilityView())
        print(f"🔁  [Availability] Persistent view re-registered — buttons survive restart.")

    # ── Poll data ─────────────────────────────────────────────────────────────

    def save_data(self):
        with open(POLL_FILE, "w") as f:
            json.dump(self.active_poll_instances, f, indent=4)

    def _load_poll_data(self) -> dict:
        if not os.path.exists(POLL_FILE):
            return {}
        try:
            with open(POLL_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    # ── Summary refresh ───────────────────────────────────────────────────────

    async def refresh_summary(self, channel: discord.TextChannel, instance: dict):
        embed  = build_summary_embed(instance)
        ch_str = str(channel.id)
        sum_id = instance.get("summary_message_id")

        try:
            last_msg = [m async for m in channel.history(limit=1)][0]
        except (IndexError, discord.Forbidden):
            last_msg = None

        if sum_id and last_msg and last_msg.id == sum_id:
            try:
                await last_msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden):
                pass

        if sum_id:
            try:
                old = await channel.fetch_message(sum_id)
                await old.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        new_msg = await channel.send(embed=embed)
        instance["summary_message_id"] = new_msg.id
        self.active_poll_instances[ch_str] = instance
        self.save_data()

    # ── Poll posting ──────────────────────────────────────────────────────────

    async def post_poll_to_channel(self, channel, league, schedule, color):
        ch_str = str(channel.id)
        instance = {
            "poll_message_id":    None,
            "summary_message_id": None,
            "availability_data":  {day: [] for day in schedule},
            "unavailable_data":   {day: [] for day in schedule},
            "schedule":           schedule,
            "color":              color.value,
            "league":             league,
        }
        self.active_poll_instances[ch_str] = instance

        await channel.send(
            f"## {RK_BANNER_TITLE} — Weekly Availability\n"
            f"*Tap the button below to mark which days you're available. All times EST/EDT.*"
        )
        poll_msg = await channel.send(view=AvailabilityView())
        instance["poll_message_id"] = poll_msg.id

        summary_msg = await channel.send(embed=build_summary_embed(instance))
        instance["summary_message_id"] = summary_msg.id
        self.save_data()

    async def _get_team_channel(self, guild, role_name):
        name = TEAM_CHANNELS.get(role_name)
        if not name:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    async def _post_league_to_all_teams(self, ctx, league):
        cfg = self.schedules.get(league)
        if not cfg:
            await ctx.send(f"❌ No schedule found for `{league}`. Known leagues: {', '.join(self.schedules.keys())}", delete_after=15)
            return

        color    = LEAGUE_COLORS.get(league, discord.Color.default())
        posted, failed = [], []

        try:
            await ctx.message.delete()
        except (discord.NotFound, AttributeError):
            pass

        if not TEAM_CHANNELS:
            await self.post_poll_to_channel(ctx.channel, league, cfg["days"], color)
            await ctx.send("⚠️ `TEAM_CHANNELS` is empty — posted here as a preview.", delete_after=15)
            return

        for role_name in TEAM_CHANNELS:
            ch = await self._get_team_channel(ctx.guild, role_name)
            if ch is None:
                failed.append(f"`{role_name}` — channel not found")
                continue
            try:
                await self.post_poll_to_channel(ch, league, cfg["days"], color)
                posted.append(f"✅ {role_name} → #{ch.name}")
            except Exception as e:
                failed.append(f"`{role_name}` — {e}")

        lines = posted + [f"❌ {r}" for r in failed]
        await ctx.send(f"**{league} posted to {len(posted)} team(s):**\n" + "\n".join(lines), delete_after=30)

    # ══════════════════════════════════════════════════════════════════════════
    #  SLASH COMMANDS — SCHEDULE EDITOR  (admin only)
    # ══════════════════════════════════════════════════════════════════════════

    schedule_group = app_commands.Group(
        name="schedule",
        description="Admin tools to edit league schedules.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @schedule_group.command(name="view", description="View current days and times for a league.")
    @app_commands.describe(league="Which league to view (e.g. RK or ITHL)")
    async def schedule_view(self, interaction: discord.Interaction, league: str):
        league = league.upper()
        cfg = self.schedules.get(league)
        if not cfg:
            await interaction.response.send_message(
                f"❌ No schedule found for `{league}`. Known leagues: {', '.join(self.schedules.keys())}",
                ephemeral=True,
            )
            return

        color = LEAGUE_COLORS.get(league, discord.Color.default())
        embed = discord.Embed(title=f"📅  {league} — Current Schedule", color=color)
        for day, times in cfg["days"].items():
            embed.add_field(name=f"🗓️ {day}", value=f"⏰ {times}", inline=False)
        embed.set_footer(text=f"Use /schedule addday or /schedule updatetimes to edit  •  {RK_BANNER_TITLE}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @schedule_group.command(name="addday", description="Add a new day (and times) to a league schedule.")
    @app_commands.describe(
        league="Which league (e.g. RK or ITHL)",
        day="Day name to add (e.g. Monday)",
        times="Game times for this day (e.g. 9:00 PM • 9:30 PM)",
    )
    async def schedule_addday(self, interaction: discord.Interaction, league: str, day: str, times: str = "TBD"):
        league = league.upper()
        day    = day.strip().title()

        if league not in self.schedules:
            self.schedules[league] = {"days": {}}

        if day in self.schedules[league]["days"]:
            await interaction.response.send_message(
                f"⚠️ `{day}` already exists in `{league}`. Use `/schedule updatetimes` to change its times.",
                ephemeral=True,
            )
            return

        self.schedules[league]["days"][day] = times
        save_schedules(self.schedules)
        print(f"📅  [Schedule] Added {day} ({times}) to {league}.")
        await interaction.response.send_message(
            f"✅ Added **{day}** → `{times}` to **{league}**.\n"
            f"Re-post availability with `/postavailability` to apply.",
            ephemeral=True,
        )

    @schedule_group.command(name="removeday", description="Remove a day from a league schedule.")
    @app_commands.describe(
        league="Which league (e.g. RK or ITHL)",
        day="Day name to remove (e.g. Monday)",
    )
    async def schedule_removeday(self, interaction: discord.Interaction, league: str, day: str):
        league = league.upper()
        day    = day.strip().title()

        if league not in self.schedules or day not in self.schedules[league]["days"]:
            await interaction.response.send_message(
                f"❌ `{day}` not found in `{league}` schedule.", ephemeral=True
            )
            return

        del self.schedules[league]["days"][day]
        save_schedules(self.schedules)
        print(f"📅  [Schedule] Removed {day} from {league}.")
        await interaction.response.send_message(
            f"✅ Removed **{day}** from **{league}**.\n"
            f"Re-post availability with `/postavailability` to apply.",
            ephemeral=True,
        )

    @schedule_group.command(name="updatetimes", description="Update the game times for an existing day.")
    @app_commands.describe(
        league="Which league (e.g. RK or ITHL)",
        day="Day to update (e.g. Friday)",
        times="New times (e.g. 9:00 PM • 9:30 PM • 10:00 PM)",
    )
    async def schedule_updatetimes(self, interaction: discord.Interaction, league: str, day: str, times: str):
        league = league.upper()
        day    = day.strip().title()

        if league not in self.schedules or day not in self.schedules[league]["days"]:
            await interaction.response.send_message(
                f"❌ `{day}` not found in `{league}`. Use `/schedule addday` first.",
                ephemeral=True,
            )
            return

        old = self.schedules[league]["days"][day]
        self.schedules[league]["days"][day] = times
        save_schedules(self.schedules)
        print(f"📅  [Schedule] Updated {league} {day}: '{old}' → '{times}'.")
        await interaction.response.send_message(
            f"✅ Updated **{league} — {day}**\n"
            f"  Before: `{old}`\n"
            f"  After:  `{times}`\n\n"
            f"Re-post availability with `/postavailability` to apply.",
            ephemeral=True,
        )

    @schedule_group.command(name="addleague", description="Create a brand new league schedule from scratch.")
    @app_commands.describe(league="New league key (e.g. OSHL)")
    async def schedule_addleague(self, interaction: discord.Interaction, league: str):
        league = league.upper()
        if league in self.schedules:
            await interaction.response.send_message(
                f"⚠️ `{league}` already exists. Use `/schedule addday` to populate it.",
                ephemeral=True,
            )
            return
        self.schedules[league] = {"days": {}}
        save_schedules(self.schedules)
        print(f"📅  [Schedule] Created new league: {league}.")
        await interaction.response.send_message(
            f"✅ Created league **{league}**.\nUse `/schedule addday` to add days to it.",
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  POST COMMANDS (unchanged logic)
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="postavailability")
    @commands.has_permissions(administrator=True)
    async def post_availability(self, ctx):
        await self._post_league_to_all_teams(ctx, "RK")

    @commands.command(name="postoshlavailability")
    @commands.has_permissions(administrator=True)
    async def post_oshl_availability(self, ctx):
        await self._post_league_to_all_teams(ctx, "ITHL")

    @app_commands.command(name="postavailability", description="Post RK weekly availability to all team channels.")
    @app_commands.default_permissions(administrator=True)
    async def slash_post_availability(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ctx = await commands.Context.from_interaction(interaction)
        await self._post_league_to_all_teams(ctx, "RK")

    @app_commands.command(name="postoshlavailability", description="Post ITHL weekly availability to all team channels.")
    @app_commands.default_permissions(administrator=True)
    async def slash_post_oshl_availability(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ctx = await commands.Context.from_interaction(interaction)
        await self._post_league_to_all_teams(ctx, "ITHL")


async def setup(bot: commands.Bot):
    print(f"🐻  [Availability] RK Grizzlies Availability Cog v{VERSION} loaded.")
    await bot.add_cog(Availability(bot))
