# ============================================================
#  OS4 League Bot — mergegames.py
#  Merge consecutive DNF games between the same two teams
#  into a single game record so players show 1 GP, not 2+.
#
#  Version : 2.1.0
#  Changes :
#    • v2.2.0: Two new features:
#      1. Already-merged games filtered from /mergegames list.
#         _filter_merged_candidates() checks both primary IDs and
#         absorbed IDs against the Merged Games tab before showing
#         candidates — no more re-showing completed merges.
#      2. /manualmerge command — specify primary + absorbed IDs
#         directly, bypassing DNF/TOI auto-detection. Use when a
#         short disconnect game pairs with a full 60-min replay
#         that the auto-scanner can't detect. Same safe v2 merge
#         logic — Player Stats never touched, stub rows written,
#         fully reversible with /unmerge.
#    • v2.1.0: Two merge-candidate fixes:
#      1. TOI threshold — games >= 55 min (3300s) are excluded from
#         merging even if technically < 3600s. A 59-min game is a
#         real completed game, not a DNF restart. Configurable via
#         DNF_MAX_SECONDS constant.
#      2. Date gap guard — consecutive DNF games must be on the same
#         calendar date to be grouped. Games days apart are different
#         sessions and should never be auto-merged.
#      3. Score display fix — confirm embed now shows each team's
#         score consistently using the same team-ID ordering across
#         all games in a group, preventing swapped home/away totals.
#    • v2.0.1: Duplicate merge guard added.
#    • v2.0.0: BREAKING FIX: No longer rewrites Match IDs in Player Stats.
#      Rewriting rows was causing GP inflation (50+ GP shown when
#      only 8 games played) and infinite season image repost loops.
#    • Merge is now stored ONLY in the "Merged Games" lookup tab.
#    • game_results-2.py reads this tab to combine games at display
#      time — raw Player Stats data is never touched.
#    • Stub rows are still written so the scanner never re-fetches
#      absorbed game IDs. This part is unchanged.
#    • /unmerge command added — fully reverses a merge by deleting
#      the lookup row (raw data was never changed so nothing to undo
#      in Player Stats).
#    • /mergedgames audit log unchanged.
#
#  ⚠️  If you ran v1.2.0 and your Player Stats rows were already
#      rewritten, you must manually restore the original Match IDs
#      in the sheet (use the Merged Games audit tab to see which
#      rows were changed). The /unmerge command handles future merges
#      safely.
# ============================================================

VERSION  = "2.3.0"
COG_NAME = "MergeGames"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading...")

import discord
from discord.ext import commands
from discord import app_commands
import utils
from datetime import datetime

# ── Constants ────────────────────────────────────────────────
REGULATION_SECONDS = 3600
# Games at or above this TOI are treated as real completed games
# even if technically < 3600s. Prevents near-full games (e.g. 59 min)
# from being included in DNF merge candidates.
DNF_MAX_SECONDS    = 3300          # 55 minutes
MERCY_GOAL_LEAD    = 7
AUDIT_TAB          = "Merged Games"
STUB_NOTE          = "[MERGED - DO NOT DELETE]"

# Column layout for the Merged Games lookup tab
# This tab is now the SOURCE OF TRUTH for merges — not Player Stats
AUDIT_COLS = ["Merged At", "Primary Match ID", "Absorbed IDs",
              "Absorbed Count", "Merged By", "Bot Version"]


# ════════════════════════════════════════════════════════════
#  LOW-LEVEL SHEET HELPERS
# ════════════════════════════════════════════════════════════

def _get_header_map(rows):
    """Return (header_row_index, {col_name: 0-based-index})."""
    for i, row in enumerate(rows):
        if "Match ID" in row or "matchid" in [c.lower() for c in row]:
            return i, {c.strip(): idx for idx, c in enumerate(row)}
    return 0, {c.strip(): idx for idx, c in enumerate(rows[0])}


def _safe_int(val):
    try:
        return int(float(str(val).replace(",", "")))
    except Exception:
        return 0


def _col_letter(idx: int) -> str:
    """0-based column index → spreadsheet letter (A, B … Z, AA …)."""
    result = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


# ════════════════════════════════════════════════════════════
#  MERGE LOOKUP TABLE  (Merged Games tab)
# ════════════════════════════════════════════════════════════

def get_merge_map(sh) -> dict:
    """
    Read the Merged Games tab and return a mapping:
        absorbed_id (str) → primary_id (str)

    Used by game_results-2.py to combine games at display time
    without touching Player Stats.
    Returns {} if the tab doesn't exist or has no rows.
    """
    try:
        ws   = sh.worksheet(AUDIT_TAB)
        rows = ws.get_all_values()
    except Exception:
        return {}

    if len(rows) <= 1:
        return {}

    merge_map = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        primary_id   = str(row[1]).strip()
        absorbed_raw = str(row[2]).strip()
        if not primary_id or not absorbed_raw:
            continue
        for aid in absorbed_raw.split(","):
            aid = aid.strip()
            if aid:
                merge_map[aid] = primary_id

    return merge_map


def _write_audit_row(sh, primary_id: str, secondary_ids: list) -> bool:
    """Append a merge record to the Merged Games tab.
    Blocks duplicate entries — if this primary_id is already present,
    nothing is written and False is returned.
    Returns True on success, False if duplicate blocked.
    """
    try:
        try:
            ws = sh.worksheet(AUDIT_TAB)
        except Exception:
            ws = sh.add_worksheet(title=AUDIT_TAB, rows=500, cols=6)
            ws.append_row(AUDIT_COLS, value_input_option="USER_ENTERED")

        # ── Duplicate guard ───────────────────────────────────
        existing = ws.get_all_values()
        for row in existing[1:]:
            if len(row) >= 2 and str(row[1]).strip() == str(primary_id).strip():
                print(f"[{COG_NAME}] Duplicate merge blocked — primary {primary_id} already exists.")
                return False

        ws.append_row(
            [
                datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                primary_id,
                ", ".join(str(s) for s in secondary_ids),
                len(secondary_ids),
                "OS4 Bot",
                f"v{VERSION}",
            ],
            value_input_option="USER_ENTERED"
        )
        return True
    except Exception as e:
        print(f"[{COG_NAME}] Audit write error: {e}")
        return False


# ════════════════════════════════════════════════════════════
#  CANDIDATE SCAN
# ════════════════════════════════════════════════════════════

def _read_dnf_games(sh):
    """
    Scan Player Stats for groups of consecutive non-mercy DNF
    games between the same two teams eligible for merging.
    Stub rows are ignored automatically.
    Returns: (candidate_groups: list, per_match: dict)
    """
    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] Sheet read error: {e}")
        return [], {}

    if not rows:
        return [], {}

    header_idx, hmap = _get_header_map(rows)

    c_mid   = hmap.get("Match ID",  -1)
    c_date  = hmap.get("Date",      -1)
    # Support both old schema (Team ID) and new schema (Team Name)
    c_tid   = hmap.get("Team Name", hmap.get("Team ID",  -1))
    # Support both old schema (TOI) and new schema (TOI Seconds / toiseconds)
    c_toi   = hmap.get("TOI Seconds", hmap.get("toiseconds", hmap.get("TOI", -1)))
    # Support both old schema (Goals) and new schema (skgoals)
    c_goals = hmap.get("skgoals",   hmap.get("Goals",    -1))
    # Support both old schema (Position) and new schema (position lowercase)
    c_pos   = hmap.get("position",  hmap.get("Position", -1))
    c_user  = hmap.get("Username",  -1)

    match_data = {}

    for row in rows[header_idx + 1:]:
        if not row or c_mid == -1 or c_mid >= len(row):
            continue
        mid = str(row[c_mid]).strip()
        if not mid:
            continue

        # Skip stub rows
        username = str(row[c_user]).strip() if c_user != -1 and c_user < len(row) else ""
        if STUB_NOTE in username:
            continue

        tid = str(row[c_tid]).strip() if c_tid != -1 and c_tid < len(row) else ""
        if not tid:
            continue

        date       = row[c_date].strip()             if c_date  != -1 and c_date  < len(row) else ""
        toiseconds = _safe_int(row[c_toi])            if c_toi   != -1 and c_toi   < len(row) else 0
        goals      = _safe_int(row[c_goals])          if c_goals != -1 and c_goals < len(row) else 0
        pos        = row[c_pos].strip()               if c_pos   != -1 and c_pos   < len(row) else ""

        if mid not in match_data:
            match_data[mid] = {"date": date, "teams": {}}
        if tid not in match_data[mid]["teams"]:
            match_data[mid]["teams"][tid] = {"score": 0, "max_toi": 0, "goalie_toi": 0}

        t = match_data[mid]["teams"][tid]
        t["score"] += goals
        if toiseconds > t["max_toi"]:
            t["max_toi"] = toiseconds
        if "goalie" in pos.lower() and toiseconds > t["goalie_toi"]:
            t["goalie_toi"] = toiseconds

    per_match = {}
    for mid, data in match_data.items():
        teams = data["teams"]
        if len(teams) < 2:
            continue

        t_ids        = list(teams.keys())
        t1_id, t2_id = t_ids[0], t_ids[1]
        s1, s2       = teams[t1_id]["score"], teams[t2_id]["score"]

        goalie_tois = [
            teams[tid]["goalie_toi"] or teams[tid]["max_toi"]
            for tid in t_ids
        ]
        toiseconds = max(goalie_tois) if goalie_tois else 0
        goal_diff  = abs(s1 - s2)

        per_match[mid] = {
            "match_id":   mid,
            "date":       data["date"],
            "team_pair":  frozenset({t1_id, t2_id}),
            "score":      {t1_id: s1, t2_id: s2},
            "goal_diff":  goal_diff,
            "toiseconds": toiseconds,
            # True DNF = started but ended well before regulation.
            # Games >= DNF_MAX_SECONDS (55 min) are real games even if
            # slightly under 60 min — exclude them from merge candidates.
            "is_dnf":     toiseconds < DNF_MAX_SECONDS,
            "is_mercy":   goal_diff >= MERCY_GOAL_LEAD,
        }

    def sort_key(mid):
        try:    return int(mid)
        except: return mid

    sorted_ids = sorted(per_match.keys(), key=sort_key)

    pair_runs = {}
    for mid in sorted_ids:
        pair_runs.setdefault(per_match[mid]["team_pair"], []).append(per_match[mid])

    candidate_groups = []
    for pair, matches in pair_runs.items():
        run = []
        for m in matches:
            if m["is_dnf"] and not m["is_mercy"]:
                # Date gap guard: only extend the run if this game is on
                # the same calendar date as the previous one in the run.
                # Games on different dates are different sessions.
                if run and m["date"] != run[-1]["date"]:
                    if len(run) >= 2:
                        candidate_groups.append({"team_pair": pair, "matches": list(run)})
                    run = [m]
                else:
                    run.append(m)
            else:
                if len(run) >= 2:
                    candidate_groups.append({"team_pair": pair, "matches": list(run)})
                run = []
        if len(run) >= 2:
            candidate_groups.append({"team_pair": pair, "matches": list(run)})

    return candidate_groups, per_match


def _filter_merged_candidates(sh, candidate_groups: list) -> list:
    """
    Remove any candidate groups where the primary (first) match ID
    already exists in the Merged Games tab. Prevents already-merged
    games from showing up again in /mergegames.
    """
    existing_map = get_merge_map(sh)
    already_primary = set()
    try:
        ws   = sh.worksheet(AUDIT_TAB)
        rows = ws.get_all_values()
        for row in rows[1:]:
            if len(row) >= 2 and row[1].strip():
                already_primary.add(row[1].strip())
    except Exception:
        pass

    filtered = []
    for group in candidate_groups:
        match_ids = {m["match_id"] for m in group["matches"]}
        # Skip if any match in the group is already a primary or absorbed ID
        if match_ids & already_primary:
            continue
        if match_ids & set(existing_map.keys()):
            continue
        filtered.append(group)
    return filtered


# ════════════════════════════════════════════════════════════
#  MERGE EXECUTION  (v2 — NO longer touches Player Stats IDs)
# ════════════════════════════════════════════════════════════

def _build_stub_row(header: dict, match_id: str, date: str, num_cols: int) -> list:
    """
    Build a blank stub row so the auto-scanner sees the absorbed ID
    as already logged and never re-fetches it.
    Stats are ALL empty so nothing gets double-counted.
    """
    row = [""] * num_cols
    if "Match ID" in header: row[header["Match ID"]] = match_id
    if "Date"     in header: row[header["Date"]]     = date
    if "Username" in header: row[header["Username"]] = STUB_NOTE
    return row


def _do_merge(sh, primary_id: str, secondary_ids: list,
              secondary_dates: dict, config: dict):
    """
    v2.0.0 — Safe merge that never rewrites Player Stats Match IDs.

    Steps:
      1. Write the merge record to the Merged Games lookup tab.
         game_results-2.py reads this tab to combine games at
         display time. Raw Player Stats data is untouched.
      2. Append stub rows for each absorbed ID so the scanner
         never re-fetches those games.

    Returns (stubs_written: int, error: str | None)
    """
    # ── Step 1: write lookup row (duplicate-guarded) ─────────
    written = _write_audit_row(sh, primary_id, secondary_ids)
    if not written:
        return 0, f"This merge already exists in the `{AUDIT_TAB}` tab. Use `/mergedgames` to review or `/unmerge` to undo it first."

    # ── Step 2: append stub rows so scanner skips absorbed IDs ─
    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
    except Exception as e:
        return 0, str(e)

    header_idx, hmap = _get_header_map(rows)
    num_cols = len(rows[header_idx]) if rows else 20

    stub_rows = []
    for sid in secondary_ids:
        date = secondary_dates.get(str(sid), "")
        stub_rows.append(_build_stub_row(hmap, str(sid), date, num_cols))

    stubs_written = 0
    if stub_rows:
        try:
            ws.append_rows(stub_rows, value_input_option="USER_ENTERED")
            stubs_written = len(stub_rows)
        except Exception as e:
            print(f"[{COG_NAME}] Stub row write error (non-fatal): {e}")

    return stubs_written, None


# ════════════════════════════════════════════════════════════
#  UNMERGE  (new in v2.0.0)
# ════════════════════════════════════════════════════════════

def _do_unmerge(sh, primary_id: str) -> tuple:
    """
    Remove a merge record from the Merged Games tab.
    Because v2.0.0 never rewrites Player Stats, this fully
    reverses the merge — no manual sheet editing needed.

    Returns (absorbed_ids: list, error: str | None)
    """
    try:
        ws   = sh.worksheet(AUDIT_TAB)
        rows = ws.get_all_values()
    except Exception as e:
        return [], str(e)

    if len(rows) <= 1:
        return [], "No merges found in audit tab."

    header = rows[0]
    try:
        col_primary  = header.index("Primary Match ID")
        col_absorbed = header.index("Absorbed IDs")
    except ValueError:
        return [], "Merged Games tab has unexpected columns."

    target_row = None
    absorbed_ids = []
    for i, row in enumerate(rows[1:], start=2):  # 1-based for gspread
        if len(row) > col_primary and str(row[col_primary]).strip() == str(primary_id).strip():
            target_row   = i
            absorbed_raw = str(row[col_absorbed]).strip() if len(row) > col_absorbed else ""
            absorbed_ids = [a.strip() for a in absorbed_raw.split(",") if a.strip()]
            break

    if target_row is None:
        return [], f"No merge record found for primary ID `{primary_id}`."

    try:
        ws.delete_rows(target_row)
    except Exception as e:
        return [], str(e)

    return absorbed_ids, None


# ════════════════════════════════════════════════════════════
#  DISCORD UI
# ════════════════════════════════════════════════════════════

class MergeConfirmView(discord.ui.View):
    def __init__(self, group: dict, config: dict, sh):
        super().__init__(timeout=120)
        self.group  = group
        self.config = config
        self.sh     = sh

    def _label(self, tid):
        return self.config.get("team_ids", {}).get(tid, tid)

    @discord.ui.button(label="✅ Confirm Merge", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        matches    = self.group["matches"]
        primary_id = matches[0]["match_id"]
        secondary  = [m["match_id"] for m in matches[1:]]
        sec_dates  = {m["match_id"]: m["date"] for m in matches[1:]}

        stubs_written, err = _do_merge(self.sh, primary_id, secondary, sec_dates, self.config)
        if err:
            return await interaction.followup.send(f"❌ Merge failed: `{err}`", ephemeral=True)

        pair     = list(self.group["team_pair"])
        t1_label = self._label(pair[0])
        t2_label = self._label(pair[1])

        embed = discord.Embed(
            title="✅ Games Merged",
            description=(
                f"**{t1_label}** vs **{t2_label}**\n\n"
                f"🎯 **Primary Match ID:** `{primary_id}`\n"
                f"🗑️ **Absorbed IDs:** `{', '.join(secondary)}`\n"
                f"🔒 **Stub rows written:** `{stubs_written}` "
                f"(scanner will skip absorbed IDs)\n\n"
                f"✅ **Player Stats rows were NOT modified.**\n"
                f"Stats are combined at display time using the "
                f"**Merged Games** lookup tab. Raw data is safe.\n\n"
                f"Players will show **1 GP** instead of **{len(matches)} GP**.\n\n"
                f"💡 Run `/updateresults` to refresh the Game Results tab.\n"
                f"↩️ Use `/unmerge primary_id:{primary_id}` to undo this merge."
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION} • Audit: '{AUDIT_TAB}' tab")
        self.clear_items()
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clear_items()
        await interaction.response.send_message("❌ Merge cancelled.", ephemeral=True)


class MergeGroupSelect(discord.ui.Select):
    def __init__(self, groups: list, config: dict, sh):
        self.groups = groups
        self.config = config
        self.sh     = sh

        team_names = config.get("team_ids", {})
        options    = []

        for idx, g in enumerate(groups[:25]):
            pair     = list(g["team_pair"])
            t1_label = team_names.get(pair[0], pair[0])
            t2_label = team_names.get(pair[1], pair[1])
            ids_str  = ", ".join(m["match_id"] for m in g["matches"])
            date_str = g["matches"][0].get("date", "?")
            scores   = " / ".join(
                f"{list(m['score'].values())[0]}-{list(m['score'].values())[1]}"
                if len(m["score"]) >= 2 else "?"
                for m in g["matches"]
            )
            label = f"{t1_label} vs {t2_label} ({len(g['matches'])} DNFs)"[:100]
            desc  = f"IDs: {ids_str} | {date_str} | {scores}"[:100]
            options.append(discord.SelectOption(label=label, description=desc, value=str(idx)))

        super().__init__(
            placeholder="⚠️ Select a group of DNF games to merge...",
            min_values=1, max_values=1,
            options=options
        )

    def _label(self, tid):
        return self.config.get("team_ids", {}).get(tid, tid)

    async def callback(self, interaction: discord.Interaction):
        idx   = int(self.values[0])
        group = self.groups[idx]

        pair     = list(group["team_pair"])
        t1_label = self._label(pair[0])
        t2_label = self._label(pair[1])

        # Use the first match's team ID ordering as the canonical reference
        # so scores are displayed consistently (same team always on left).
        first_score = group["matches"][0]["score"]
        canonical_ids = list(first_score.keys())   # [team_a_id, team_b_id]

        lines = []
        for i, m in enumerate(group["matches"]):
            tmin = round(m["toiseconds"] / 60, 1)
            # Always show score in canonical order regardless of dict insertion
            s0 = m["score"].get(canonical_ids[0], 0) if len(canonical_ids) > 0 else 0
            s1 = m["score"].get(canonical_ids[1], 0) if len(canonical_ids) > 1 else 0
            s_str = f"{s0}-{s1}"
            role  = "🟢 PRIMARY (kept)" if i == 0 else f"🔴 Absorbed → `{group['matches'][0]['match_id']}`"
            lines.append(f"`{m['match_id']}` | {s_str} | {tmin} min | {m['date']} | {role}")

        # Combined score using same canonical ordering
        total_t1 = sum(m["score"].get(canonical_ids[0], 0) for m in group["matches"])
        total_t2 = sum(m["score"].get(canonical_ids[1], 0) for m in group["matches"] if len(canonical_ids) > 1)
        total_min = round(sum(m["toiseconds"] for m in group["matches"]) / 60, 1)

        embed = discord.Embed(
            title=f"⚠️ Confirm Merge — {t1_label} vs {t2_label}",
            description=(
                f"The following **{len(group['matches'])} DNF games** will be merged:\n\n"
                + "\n".join(lines)
                + f"\n\n**Combined score:** `{total_t1} - {total_t2}`"
                + f"\n**Combined TOI:** `{total_min} min`"
                + f"\n**Players will show:** `1 GP` instead of `{len(group['matches'])} GP`"
                + "\n\n✅ **Player Stats rows are NOT modified** (v2.0.0 safe merge).\n"
                + "🔒 Stub rows added for absorbed IDs — scanner ignores them.\n"
                + f"📋 Merge record saved to **`{AUDIT_TAB}`** tab.\n"
                + "↩️ This can be undone with `/unmerge`."
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION}")
        await interaction.response.send_message(
            embed=embed,
            view=MergeConfirmView(group, self.config, self.sh),
            ephemeral=True
        )


class MergeGroupView(discord.ui.View):
    def __init__(self, groups, config, sh):
        super().__init__(timeout=180)
        self.add_item(MergeGroupSelect(groups, config, sh))


class ManualMergeConfirmView(discord.ui.View):
    def __init__(self, primary_id: str, secondary: list,
                 sec_dates: dict, config: dict, sh):
        super().__init__(timeout=120)
        self.primary_id = primary_id
        self.secondary  = secondary
        self.sec_dates  = sec_dates
        self.config     = config
        self.sh         = sh

    @discord.ui.button(label="✅ Confirm Manual Merge", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        stubs_written, err = _do_merge(
            self.sh, self.primary_id, self.secondary,
            self.sec_dates, self.config)

        if err:
            return await interaction.followup.send(
                f"❌ Merge failed: `{err}`", ephemeral=True)

        embed = discord.Embed(
            title="✅ Manual Merge Complete",
            description=(
                f"🎯 **Primary Match ID:** `{self.primary_id}`\n"
                f"🗑️ **Absorbed IDs:** `{', '.join(self.secondary)}`\n"
                f"🔒 **Stub rows written:** `{stubs_written}`\n\n"
                f"✅ Player Stats rows were NOT modified.\n"
                f"Stats combined at display time via **Merged Games** tab.\n\n"
                f"💡 Run `/updateresults` to refresh the Game Results tab.\n"
                f"↩️ Use `/unmerge primary_id:{self.primary_id}` to undo."
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION} • Manual")
        self.clear_items()
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clear_items()
        await interaction.response.send_message("❌ Cancelled.", ephemeral=True)


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class MergeGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print(f"🏒 [{COG_NAME}] Cog initialized — v{VERSION}")

    @app_commands.command(
        name="mergegames",
        description="[Admin] Merge consecutive DNF games between the same two teams into one record."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mergegames(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        sh = utils.get_sheet()
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)

        await interaction.followup.send("🔍 Scanning Player Stats for mergeable DNF games...", ephemeral=True)

        groups, _ = _read_dnf_games(sh)
        groups    = _filter_merged_candidates(sh, groups)

        if not groups:
            embed = discord.Embed(
                title="✅ No Mergeable Games Found",
                description=(
                    "No consecutive DNF games between the same two teams were found.\n\n"
                    "**Criteria:**\n"
                    "• Game must be DNF (ended before regulation — < 60 min)\n"
                    "• 2+ DNF games in a row between the same pair of teams\n"
                    f"• Goal difference under `{MERCY_GOAL_LEAD}` "
                    f"(mercy games are never merged)"
                ),
                color=discord.Color.green()
            )
            embed.set_footer(text=f"OS4 League • MergeGames v{VERSION}")
            return await interaction.followup.send(embed=embed, ephemeral=True)

        total_matches = sum(len(g["matches"]) for g in groups)
        team_names    = self.bot.config.get("team_ids", {})

        pair_lines = []
        for g in groups:
            pair  = list(g["team_pair"])
            t1_l  = team_names.get(pair[0], pair[0])
            t2_l  = team_names.get(pair[1], pair[1])
            ids   = ", ".join(m["match_id"] for m in g["matches"])
            pair_lines.append(f"• **{t1_l}** vs **{t2_l}** — `{ids}`")

        embed = discord.Embed(
            title="🔀 Mergeable DNF Games Found",
            description=(
                f"Found **{len(groups)} group(s)** (`{total_matches}` match IDs).\n"
                f"Mercy games (≥ {MERCY_GOAL_LEAD}-goal lead) excluded automatically.\n\n"
                + "\n".join(pair_lines)
                + "\n\n**Select a group below to review and merge.**"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION} • Admin only")
        await interaction.followup.send(
            embed=embed,
            view=MergeGroupView(groups, self.bot.config, sh),
            ephemeral=True
        )

    @app_commands.command(
        name="unmerge",
        description="[Admin] Undo a previous merge by its primary Match ID."
    )
    @app_commands.describe(primary_id="The primary Match ID that was kept after the merge.")
    @app_commands.checks.has_permissions(administrator=True)
    async def unmerge(self, interaction: discord.Interaction, primary_id: str):
        await interaction.response.defer(ephemeral=True)

        sh = utils.get_sheet()
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)

        absorbed_ids, err = _do_unmerge(sh, primary_id.strip())
        if err:
            return await interaction.followup.send(f"❌ Unmerge failed: `{err}`", ephemeral=True)

        embed = discord.Embed(
            title="↩️ Merge Undone",
            description=(
                f"🎯 **Primary Match ID:** `{primary_id}`\n"
                f"🔓 **Absorbed IDs restored:** `{', '.join(absorbed_ids)}`\n\n"
                f"The merge record has been removed from **`{AUDIT_TAB}`**.\n"
                f"Since v2.0.0 never modified Player Stats, no row edits were needed.\n\n"
                f"💡 Run `/updateresults` to refresh the Game Results tab."
            ),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="mergedgames",
        description="[Admin] View the audit log of previously merged games."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mergedgames(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        sh = utils.get_sheet()
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)

        try:
            ws   = sh.worksheet(AUDIT_TAB)
            rows = ws.get_all_values()
        except Exception:
            return await interaction.followup.send(
                f"📋 No merges performed yet. `{AUDIT_TAB}` tab doesn't exist.", ephemeral=True
            )

        if len(rows) <= 1:
            return await interaction.followup.send("📋 No merges recorded yet.", ephemeral=True)

        lines = []
        for row in rows[1:][-15:]:
            if len(row) >= 3:
                lines.append(
                    f"`{row[0]}` | Primary: `{row[1]}` | Absorbed: `{row[2]}`"
                )

        embed = discord.Embed(
            title=f"📋 {AUDIT_TAB} — Last {len(lines)} Entries",
            description="\n".join(lines) or "No records.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION} • Full log in sheet")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="manualmerge",
        description="[Admin] Manually merge any two match IDs — bypasses DNF/TOI requirements."
    )
    @app_commands.describe(
        primary_id="The match ID to KEEP (the real completed game)",
        absorbed_ids="Comma-separated match IDs to absorb (e.g. '12345,67890')"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def manualmerge(self, interaction: discord.Interaction,
                          primary_id: str, absorbed_ids: str):
        await interaction.response.defer(ephemeral=True)

        sh = utils.get_sheet()
        if not sh:
            return await interaction.followup.send(
                "❌ Could not connect to Google Sheets.", ephemeral=True)

        primary_id   = primary_id.strip()
        secondary    = [s.strip() for s in absorbed_ids.split(",") if s.strip()]

        if not primary_id or not secondary:
            return await interaction.followup.send(
                "❌ You must provide both a primary ID and at least one absorbed ID.",
                ephemeral=True)

        # Look up dates for absorbed IDs from Player Stats (for stub rows)
        sec_dates = {}
        try:
            ws   = sh.worksheet("Player Stats")
            rows = ws.get_all_values()
            header_idx, hmap = _get_header_map(rows)
            c_mid  = hmap.get("Match ID", -1)
            c_date = hmap.get("Date", -1)
            for row in rows[header_idx + 1:]:
                if c_mid != -1 and c_mid < len(row):
                    mid = str(row[c_mid]).strip()
                    if mid in secondary and c_date != -1 and c_date < len(row):
                        sec_dates[mid] = row[c_date].strip()
        except Exception as e:
            print(f"[{COG_NAME}] manualmerge date lookup error: {e}")

        # Show confirmation before executing
        embed = discord.Embed(
            title="⚠️ Confirm Manual Merge",
            description=(
                f"🎯 **Primary (keep):** `{primary_id}`\n"
                f"🗑️ **Absorb:** `{', '.join(secondary)}`\n\n"
                f"This bypasses DNF/TOI checks — use when the auto-scanner\n"
                f"couldn't detect the pairing (e.g. a short disconnect game\n"
                f"paired with a full 60-min replay).\n\n"
                f"✅ Player Stats rows are NOT modified.\n"
                f"↩️ Can be undone with `/unmerge primary_id:{primary_id}`"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"OS4 League • MergeGames v{VERSION} • Manual")

        view = ManualMergeConfirmView(
            primary_id, secondary, sec_dates, self.bot.config, sh)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @manualmerge.error
    async def manualmerge_error(self, interaction, error):
        msg = ("❌ Administrator permission required."
               if isinstance(error, app_commands.MissingPermissions)
               else f"❌ Error: `{error}`")
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    @mergegames.error
    async def mergegames_error(self, interaction, error):
        msg = ("❌ Administrator permission required."
               if isinstance(error, app_commands.MissingPermissions)
               else f"❌ Error: `{error}`")
        await interaction.response.send_message(msg, ephemeral=True)

    @unmerge.error
    async def unmerge_error(self, interaction, error):
        msg = ("❌ Administrator permission required."
               if isinstance(error, app_commands.MissingPermissions)
               else f"❌ Error: `{error}`")
        await interaction.response.send_message(msg, ephemeral=True)

    @mergedgames.error
    async def mergedgames_error(self, interaction, error):
        msg = ("❌ Administrator permission required."
               if isinstance(error, app_commands.MissingPermissions)
               else f"❌ Error: `{error}`")
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(MergeGames(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
