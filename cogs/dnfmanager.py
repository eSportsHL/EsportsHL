# ============================================================
#  Echelon League Bot — dnfmanager.py
#  Version: 2.0.0
#  NEW COG — Never modifies utils.py, lagout.py, or any existing cog.
#
#  Flow:
#    1. statslogger detects DNF → queues notification
#    2. DNFManager checks Player Stats for existing DNF between
#       same two teams on the same date
#    3a. Rematch already logged → show Merge menu (pick primary)
#    3b. No rematch yet        → show Pending menu:
#         ⏳ Watch for Rematch | 🗑️ Delete | ⏸️ Dismiss
#    4. "Watch" stores pair in dnf_pairs.json, background task
#       polls every 60s. When rematch found → auto-show merge menu
#    5. After 1 hour with no rematch → reminder ping
#    6. Mercy W/L → clean notification only, no merge options
#
#  Merge uses lagout._do_merge (safe v2 — never touches Player Stats)
#  Undo  uses lagout._do_unmerge
#
#  Changelog:
#    v2.0.0 — Full smart DNF menu. Auto-pair detection. 1-hour reminder.
#              Mercy tagging. Undo button after merge.
#    v1.0.0 — Basic approve/reject workflow (removed).
# ============================================================

VERSION  = "2.0.1"
COG_NAME = "DNFManager"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Smart DNF menu")

import os
import json
import asyncio
import utils
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone

BASE_DIR      = os.path.dirname(os.path.abspath(utils.__file__))
PAIRS_FILE    = os.path.join(BASE_DIR, "dnf_pairs.json")
WATCH_TIMEOUT = 3600   # 1 hour in seconds
DNF_MAX_TOI   = 3300   # matches lagout.py
MERCY_GOALS   = 7

# ════════════════════════════════════════════════════════════
#  PAIRS FILE HELPERS
# ════════════════════════════════════════════════════════════

def _load_pairs() -> dict:
    if not os.path.exists(PAIRS_FILE):
        return {}
    try:
        with open(PAIRS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_pairs(data: dict):
    with open(PAIRS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _add_pair(mid: str, entry: dict):
    data = _load_pairs()
    data[str(mid)] = entry
    _save_pairs(data)


def _remove_pair(mid: str):
    data = _load_pairs()
    data.pop(str(mid), None)
    _save_pairs(data)


# ════════════════════════════════════════════════════════════
#  SHEET HELPERS
# ════════════════════════════════════════════════════════════

def _get_dnf_games_for_pair(team1: str, team2: str, date: str) -> list:
    """
    Find all games between team1 and team2 on the given date (any TOI).
    Returns list of {match_id, team1, team2, score1, score2, toi, date}
    Uses new schema column names.
    """
    results = []
    try:
        sh = utils.get_sheet()
        if not sh:
            return results
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Match ID", "Username"])
        if h_idx == -1:
            return results

        def col(n):
            try:    return h.index(n)
            except: return -1

        c_mid  = col("Match ID")
        c_team = col("Team Name")
        c_date = col("Date")
        c_toi  = col("TOI Seconds")
        c_score = col("Score")
        c_user  = col("Username")
        c_res   = col("Result")

        match_data = {}
        for row in rows[h_idx + 1:]:
            if not row or c_mid == -1 or c_mid >= len(row):
                continue
            mid = str(row[c_mid]).strip()
            if not mid:
                continue
            # Skip stubs
            uval = str(row[c_user]).strip() if c_user != -1 and c_user < len(row) else ""
            if "[MERGED" in uval or "[DNF" in uval:
                continue
            row_date = str(row[c_date]).strip()[:10] if c_date != -1 and c_date < len(row) else ""
            if row_date != date[:10]:
                continue
            tname = str(row[c_team]).strip() if c_team != -1 and c_team < len(row) else ""
            try:
                toi = int(float(str(row[c_toi]).strip())) if c_toi != -1 and c_toi < len(row) else 0
            except Exception:
                toi = 0
            try:
                score = int(float(str(row[c_score]).strip())) if c_score != -1 and c_score < len(row) else 0
            except Exception:
                score = 0
            res = str(row[c_res]).strip() if c_res != -1 and c_res < len(row) else ""

            if mid not in match_data:
                match_data[mid] = {"toi": toi, "teams": {}, "date": row_date, "result": res}
            if tname and tname not in match_data[mid]["teams"]:
                match_data[mid]["teams"][tname] = score
            if toi > match_data[mid]["toi"]:
                match_data[mid]["toi"] = toi

        t1l, t2l = team1.lower(), team2.lower()
        for mid, data in match_data.items():
            tnames = list(data["teams"].keys())
            tnames_lower = [t.lower() for t in tnames]
            if not (t1l in tnames_lower and t2l in tnames_lower):
                continue
            # Include all games between these teams — rematch may be a full game
            scores = list(data["teams"].values())
            results.append({
                "match_id": mid,
                "team1":    tnames[0],
                "team2":    tnames[1] if len(tnames) > 1 else "?",
                "score1":   scores[0],
                "score2":   scores[1] if len(scores) > 1 else 0,
                "toi":      data["toi"],
                "date":     data["date"],
            })

    except Exception as e:
        print(f"[{COG_NAME}] _get_dnf_games_for_pair error: {e}")

    return results


def _do_merge_games(primary_id: str, secondary_ids: list, secondary_dates: dict, config: dict):
    """Call lagout._do_merge directly."""
    try:
        from cogs.lagout import _do_merge
        sh = utils.get_sheet()
        if not sh:
            return 0, "Could not connect to Google Sheets."
        stubs, err = _do_merge(sh, primary_id, secondary_ids, secondary_dates, config)
        return stubs, err
    except Exception as e:
        return 0, str(e)


def _do_unmerge_game(primary_id: str):
    """Call lagout._do_unmerge directly."""
    try:
        from cogs.lagout import _do_unmerge
        sh = utils.get_sheet()
        if not sh:
            return [], "Could not connect to Google Sheets."
        return _do_unmerge(sh, primary_id)
    except Exception as e:
        return [], str(e)


def _fmt_toi(toi: int) -> str:
    return f"{toi // 60}:{toi % 60:02d}"


# ════════════════════════════════════════════════════════════
#  MERGE VIEW  (pick primary + confirm)
# ════════════════════════════════════════════════════════════

class MergeView(discord.ui.View):
    """Shown when two DNF games are ready to merge. Admin picks primary."""

    def __init__(self, games: list, config: dict, bot):
        super().__init__(timeout=3600)
        self.games   = games   # list of game dicts
        self.config  = config
        self.bot     = bot
        self.primary = None    # set by select

        options = []
        for g in games[:25]:
            label = (f"#{g['match_id'][-8:]}  |  "
                     f"{g['team1']} {g['score1']} - {g['score2']} {g['team2']}  |  "
                     f"{_fmt_toi(g['toi'])} min")
            options.append(discord.SelectOption(
                label=label[:100],
                value=g["match_id"],
                description=f"Date: {g['date']}  TOI: {_fmt_toi(g['toi'])}"
            ))

        self.select = discord.ui.Select(
            placeholder="1️⃣ Choose PRIMARY game (stats kept under this ID)...",
            options=options,
            custom_id="dnf_primary_select"
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        self.primary = self.values[0] if hasattr(self, 'values') else self.select.values[0]
        self.primary = self.select.values[0]
        await interaction.response.defer()
        # Enable merge button
        self.merge_btn.disabled = False
        await interaction.message.edit(view=self)

    @discord.ui.button(label="✅ Merge Games", style=discord.ButtonStyle.success,
                       custom_id="dnf_merge_btn", disabled=True)
    async def merge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        if not self.primary:
            return await interaction.response.send_message("❌ Select a primary game first.", ephemeral=True)

        await interaction.response.defer()

        secondary = [g["match_id"] for g in self.games if g["match_id"] != self.primary]
        sec_dates = {g["match_id"]: g["date"] for g in self.games if g["match_id"] != self.primary}
        primary_game = next((g for g in self.games if g["match_id"] == self.primary), self.games[0])

        stubs, err = _do_merge_games(self.primary, secondary, sec_dates, self.config)
        if err:
            return await interaction.followup.send(f"❌ Merge failed: `{err}`")

        # Disable all buttons, show undo
        for child in self.children:
            child.disabled = True
        self.add_item(UndoMergeButton(self.primary))

        embed = discord.Embed(
            title="✅ DNF Games Merged",
            description=(
                f"**Primary:** `{self.primary}` — "
                f"{primary_game['team1']} `{primary_game['score1']}` — "
                f"`{primary_game['score2']}` {primary_game['team2']}\n"
                f"**Absorbed:** `{', '.join(secondary)}`\n\n"
                f"Players will show **1 GP**. Run `/updateresults` to refresh.\n"
                f"Use the ↩️ button below to undo if needed."
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"DNFManager v{VERSION}")
        await interaction.message.edit(embed=embed, view=self)

        # Remove from watch pairs if present
        for sec in secondary:
            _remove_pair(sec)
        _remove_pair(self.primary)

        await utils.send_log(self.bot,
            f"🔀 DNF Merge: `{self.primary}` ← `{', '.join(secondary)}` by {interaction.user}"
        )

    @discord.ui.button(label="⏸️ Dismiss", style=discord.ButtonStyle.secondary,
                       custom_id="dnf_merge_dismiss")
    async def dismiss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="⏸️ Dismissed — stats remain as separate games.",
            view=self
        )


class UndoMergeButton(discord.ui.Button):
    def __init__(self, primary_id: str):
        super().__init__(
            label="↩️ Undo Merge",
            style=discord.ButtonStyle.danger,
            custom_id=f"dnf_undo_{primary_id}"
        )
        self.primary_id = primary_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        await interaction.response.defer()

        absorbed, err = _do_unmerge_game(self.primary_id)
        if err:
            return await interaction.followup.send(f"❌ Undo failed: `{err}`")

        self.disabled = True
        await interaction.message.edit(
            content=(f"↩️ **Merge undone** by {interaction.user.mention}\n"
                     f"Primary `{self.primary_id}` unmerged. "
                     f"Absorbed IDs restored: `{', '.join(absorbed)}`\n"
                     f"Run `/updateresults` to refresh."),
            view=self.view
        )


# ════════════════════════════════════════════════════════════
#  PENDING VIEW  (no rematch yet)
# ════════════════════════════════════════════════════════════

class PendingView(discord.ui.View):
    """Shown when a DNF is logged but no rematch found yet."""

    def __init__(self, mid: str, team1: str, team2: str,
                 score1: int, score2: int, toi: int,
                 date: str, config: dict, bot):
        super().__init__(timeout=None)
        self.mid    = mid
        self.team1  = team1
        self.team2  = team2
        self.score1 = score1
        self.score2 = score2
        self.toi    = toi
        self.date   = date
        self.config = config
        self.bot    = bot

    @discord.ui.button(label="⏳ Watch for Rematch", style=discord.ButtonStyle.primary,
                       custom_id="dnf_watch")
    async def watch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        entry = {
            "match_id":   self.mid,
            "team1":      self.team1,
            "team2":      self.team2,
            "score1":     self.score1,
            "score2":     self.score2,
            "toi":        self.toi,
            "date":       self.date,
            "channel_id": interaction.channel_id,
            "message_id": interaction.message.id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reminded":   False,
        }
        _add_pair(self.mid, entry)

        button.disabled   = True
        button.label      = "⏳ Watching for rematch..."
        button.style      = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"👀 Watching for rematch between **{self.team1}** and **{self.team2}**.\n"
            f"Auto-merge menu will appear when rematch is detected (1 hour timeout).",
            ephemeral=True
        )

    @discord.ui.button(label="🗑️ Delete Game", style=discord.ButtonStyle.danger,
                       custom_id="dnf_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        await interaction.response.defer()

        # Delete rows from Player Stats
        try:
            sh = utils.get_sheet()
            if sh:
                ws   = sh.worksheet("Player Stats")
                rows = ws.get_all_values()
                to_delete = []
                for i, row in enumerate(rows, start=1):
                    if row and str(row[0]).strip() == str(self.mid):
                        to_delete.append(i)
                # Delete in reverse order to preserve row indices
                for row_idx in reversed(to_delete):
                    ws.delete_rows(row_idx)
        except Exception as e:
            return await interaction.followup.send(f"❌ Delete failed: `{e}`")

        for child in self.children:
            child.disabled = True
        _remove_pair(self.mid)
        await interaction.message.edit(
            content=f"🗑️ **Game `{self.mid}` deleted** by {interaction.user.mention}.",
            view=self
        )

    @discord.ui.button(label="⏸️ Dismiss", style=discord.ButtonStyle.secondary,
                       custom_id="dnf_pending_dismiss")
    async def dismiss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        _remove_pair(self.mid)
        await interaction.response.edit_message(
            content="⏸️ Dismissed — stats remain, no merge action taken.",
            view=self
        )


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class DNFManager(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._watch_loop.start()
        print(f"🏒 [{COG_NAME}] Cog initialized — v{VERSION}")

    def cog_unload(self):
        self._watch_loop.cancel()

    # ── public entry point called by statslogger ──────────────

    async def handle_dnf(self, mid: str, game: dict, config: dict):
        """
        Called by statslogger after a DNF game is written to the sheet.
        Determines if this is a mercy, an auto-mergeable pair, or pending.
        """
        channel = self._get_dnf_channel()
        if not channel:
            print(f"[{COG_NAME}] No DNF channel set — skipping notification for {mid}")
            return

        clubs  = game.get("clubs", {})
        cids   = list(clubs.keys())
        if len(cids) < 2:
            return

        def _name(cid):
            return (
                config.get("team_ids", {}).get(str(cid))
                or clubs.get(cid, {}).get("details", {}).get("name", f"Team {cid}")
            )

        t1, t2   = cids[0], cids[1]
        n1, n2   = _name(t1), _name(t2)
        s1       = int(float(clubs.get(t1, {}).get("score", 0)))
        s2       = int(float(clubs.get(t2, {}).get("score", 0)))
        toi      = self._game_toi(game)
        date_str = datetime.now().strftime("%Y-%m-%d")
        role_ping = self._get_role_ping()

        # ── Mercy — clean notification only ──────────────────
        if abs(s1 - s2) >= MERCY_GOALS:
            winner = n1 if s1 > s2 else n2
            embed  = discord.Embed(
                title="🏒 Mercy Rule — Game Complete",
                description=(
                    f"**{n1}** `{s1}` — `{s2}` **{n2}**\n"
                    f"**Match ID:** `{mid}`\n\n"
                    f"⚡ Goal differential ≥ {MERCY_GOALS} — counted as a real **W/L**.\n"
                    f"Stats written. No merge needed."
                ),
                color=discord.Color.gold()
            )
            embed.set_footer(text=f"DNFManager v{VERSION}")
            content = f"{role_ping} — Mercy rule" if role_ping else "🏒 Mercy rule"
            await channel.send(content=content, embed=embed)
            return

        # ── Check for existing DNF between same teams today ──
        existing = _get_dnf_games_for_pair(n1, n2, date_str)
        # exclude current game
        existing = [g for g in existing if g["match_id"] != mid]

        if existing:
            # Rematch already logged — show merge menu
            current_game = {
                "match_id": mid, "team1": n1, "team2": n2,
                "score1": s1, "score2": s2, "toi": toi, "date": date_str
            }
            all_games = existing + [current_game]

            embed = discord.Embed(
                title="🔀 DNF Rematch Detected — Ready to Merge",
                description=self._format_games_list(all_games) + (
                    f"\n\n**Select the PRIMARY game** (its Match ID will be kept).\n"
                    f"The other game's stats will be combined into it at display time."
                ),
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"DNFManager v{VERSION}")
            view    = MergeView(all_games, config, self.bot)
            content = f"{role_ping} — DNF rematch ready to merge" if role_ping else "🔀 DNF rematch ready"
            await channel.send(content=content, embed=embed, view=view)

        else:
            # No rematch yet — show pending menu
            embed = discord.Embed(
                title="⚠️ DNF Game Logged",
                description=(
                    f"**{n1}** `{s1}` — `{s2}` **{n2}**\n"
                    f"**Match ID:** `{mid}`\n"
                    f"**TOI:** {_fmt_toi(toi)} min\n\n"
                    f"Stats are written to the sheet.\n"
                    f"No rematch found yet for today."
                ),
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"DNFManager v{VERSION}")
            view = PendingView(mid, n1, n2, s1, s2, toi, date_str, config, self.bot)
            content = f"{role_ping} — DNF game logged" if role_ping else "⚠️ DNF game logged"
            await channel.send(content=content, embed=embed, view=view)

    # ── background watch loop ─────────────────────────────────

    @tasks.loop(seconds=60)
    async def _watch_loop(self):
        """Poll for rematches on watched DNF pairs. Remind after 1 hour."""
        pairs = _load_pairs()
        if not pairs:
            return

        now     = datetime.now(timezone.utc)
        to_remove = []

        for mid, entry in pairs.items():
            try:
                created = datetime.fromisoformat(entry["created_at"])
                elapsed = (now - created).total_seconds()

                team1 = entry["team1"]
                team2 = entry["team2"]
                date  = entry["date"]

                # Check for rematch
                existing = _get_dnf_games_for_pair(team1, team2, date)
                existing = [g for g in existing if g["match_id"] != mid]

                if existing:
                    # Rematch found — post merge menu
                    channel = self._get_dnf_channel()
                    if channel:
                        current_game = {
                            "match_id": mid,
                            "team1": team1, "team2": team2,
                            "score1": entry["score1"], "score2": entry["score2"],
                            "toi": entry["toi"], "date": date
                        }
                        all_games = existing + [current_game]
                        config    = self.bot.config

                        # Update original message if possible
                        try:
                            orig_ch  = self.bot.get_channel(int(entry.get("channel_id", 0)))
                            orig_msg = await orig_ch.fetch_message(int(entry.get("message_id", 0)))
                            for child in orig_msg.components:
                                pass  # can't easily disable, just send new message
                        except Exception:
                            pass

                        embed = discord.Embed(
                            title="🔀 Rematch Detected — Ready to Merge",
                            description=self._format_games_list(all_games) + (
                                f"\n\n**Select the PRIMARY game** then click ✅ Merge."
                            ),
                            color=discord.Color.green()
                        )
                        embed.set_footer(text=f"DNFManager v{VERSION}")
                        view    = MergeView(all_games, config, self.bot)
                        ping    = self._get_role_ping()
                        content = f"{ping} — Rematch detected, merge ready" if ping else "🔀 Rematch detected"
                        await channel.send(content=content, embed=embed, view=view)

                    to_remove.append(mid)

                elif elapsed > WATCH_TIMEOUT and not entry.get("reminded"):
                    # 1 hour elapsed — send reminder
                    channel = self._get_dnf_channel()
                    if channel:
                        ping = self._get_role_ping()
                        await channel.send(
                            content=f"{ping} — ⏰ Reminder" if ping else "⏰ Reminder",
                            embed=discord.Embed(
                                title="⏰ DNF Watch Reminder — 1 Hour Elapsed",
                                description=(
                                    f"Still watching for rematch: **{team1}** vs **{team2}**\n"
                                    f"Original DNF: `{mid}`  |  Date: {date}\n\n"
                                    f"No rematch detected yet. Use `/mergegames` manually "
                                    f"if the rematch was played or `/unmerge` if needed."
                                ),
                                color=discord.Color.red()
                            )
                        )
                    entry["reminded"] = True
                    _save_pairs(pairs)

            except Exception as e:
                print(f"[{COG_NAME}] watch loop error for {mid}: {e}")

        for mid in to_remove:
            _remove_pair(mid)

    @_watch_loop.before_loop
    async def _before_watch(self):
        await self.bot.wait_until_ready()

    # ── helpers ───────────────────────────────────────────────

    def _get_dnf_channel(self) -> discord.TextChannel | None:
        cid = self.bot.config.get("dnf_channel_id", 0)
        if not cid:
            return None
        return self.bot.get_channel(int(cid))

    def _get_role_ping(self) -> str:
        rid = self.bot.config.get("dnf_role_id", 0)
        return f"<@&{rid}>" if rid else ""

    def _game_toi(self, game: dict) -> int:
        max_toi = 0
        for players in game.get("players", {}).values():
            for p in players.values():
                try:
                    t = int(float(p.get("toiseconds", 0)))
                    if t > max_toi:
                        max_toi = t
                except (ValueError, TypeError):
                    pass
        return max_toi

    def _format_games_list(self, games: list) -> str:
        lines = []
        for i, g in enumerate(games, 1):
            lines.append(
                f"`{i}.` **{g['team1']}** `{g['score1']}` — `{g['score2']}` **{g['team2']}**  "
                f"|  TOI: {_fmt_toi(g['toi'])}  |  ID: `{g['match_id']}`"
            )
        return "\n".join(lines)

    # ── slash commands ────────────────────────────────────────

    @app_commands.command(
        name="setdnfchannel",
        description="[Admin] Set this channel as the DNF notification channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setdnfchannel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.config["dnf_channel_id"] = interaction.channel_id
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ DNF channel set to <#{interaction.channel_id}>.", ephemeral=True
        )

    @app_commands.command(
        name="setdnfrole",
        description="[Admin] Set the staff role to ping for DNF alerts."
    )
    @app_commands.describe(role="The role to ping when a DNF game is logged")
    @app_commands.checks.has_permissions(administrator=True)
    async def setdnfrole(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        self.bot.config["dnf_role_id"] = role.id
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ DNF staff role set to {role.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="pendingdnf",
        description="[Admin] List all DNF games currently being watched for rematches."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pendingdnf(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pairs = _load_pairs()
        if not pairs:
            return await interaction.followup.send("✅ No DNF games currently being watched.", ephemeral=True)

        lines = []
        for mid, e in pairs.items():
            created  = datetime.fromisoformat(e["created_at"])
            elapsed  = (datetime.now(timezone.utc) - created).total_seconds()
            elapsed_str = f"{int(elapsed // 60)}m ago"
            lines.append(
                f"• `{mid}` — **{e['team1']}** vs **{e['team2']}**  |  "
                f"{e['date']}  |  started {elapsed_str}"
            )

        embed = discord.Embed(
            title=f"⏳ Watching {len(pairs)} DNF Game(s)",
            description="\n".join(lines),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"DNFManager v{VERSION}  •  Auto-expires after 1 hour")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setdnfchannel.error
    @setdnfrole.error
    @pendingdnf.error
    async def _admin_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DNFManager(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
