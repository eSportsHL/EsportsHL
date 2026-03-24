# ============================================================
#  Echelon League Bot — statslogger.py
#  Version: 1.4.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Changelog:
#    v1.4.0 — REMOVED DNF hold entirely. All games write immediately.
#              DNF routed to DNFManager.handle_dnf for smart menu.
#              No more dnf.json, stub rows, or approval workflow.
#    v1.3.0 — DNF hold workflow (removed).
#    v1.2.0 — Info block (Match ID, Username, Date, Result, etc.)
#    v1.1.0 — 65-column EA API schema.
#    v1.0.0 — Initial release.
# ============================================================

VERSION  = "1.4.1"
COG_NAME = "StatsLogger"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — all games write immediately")

import os
import utils
from datetime import datetime
from discord.ext import commands
import discord

BASE_DIR = os.path.dirname(os.path.abspath(utils.__file__))

MERCY_THRESHOLD = 7
DNF_MAX_SECONDS = 3300
OT_MIN_SECONDS  = 3600


def _calc_result(our_score, opp_score, toiseconds):
    try:
        our = int(float(our_score))
        opp = int(float(opp_score))
        toi = int(float(toiseconds))
    except (ValueError, TypeError):
        return ""
    diff = our - opp
    won  = diff > 0
    if abs(diff) >= MERCY_THRESHOLD:
        return "Mercy W" if won else "Mercy L"
    if toi < DNF_MAX_SECONDS:
        return "DNF"
    if toi > OT_MIN_SECONDS:
        return "OTW" if won else "OTL"
    return "W" if won else "L"


def _game_toi(game):
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


def _is_dnf(game):
    toi    = _game_toi(game)
    scores = {
        cid: int(float(data.get("score", 0)))
        for cid, data in game.get("clubs", {}).items()
    }
    if len(scores) >= 2:
        vals = list(scores.values())
        if abs(vals[0] - vals[1]) >= MERCY_THRESHOLD:
            return False  # mercy — not a DNF
    return toi < DNF_MAX_SECONDS


# ════════════════════════════════════════════════════════════
#  COLUMN SCHEMA  (65 columns)
# ════════════════════════════════════════════════════════════

INFO_HEADERS = [
    "Match ID", "Username", "Player ID", "Date",
    "Team Name", "Score", "Opponent Score", "TOI Seconds", "Result",
]

STAT_HEADERS = [
    "glbrksavepct", "glbrksaves", "glbrkshots",
    "gldsaves", "glga", "glgaa",
    "glpensavepct", "glpensaves", "glpenshots",
    "glpkclearzone", "glpokechecks",
    "glsavepct", "glsaves", "glshots", "glsoperiods",
    "opponentClubId", "opponentScore", "opponentTeamId",
    "pNhlOnlineGameType", "position", "posSorted",
    "ratingDefense", "ratingOffense", "ratingTeamplay",
    "result", "score", "scoreRaw", "scoreString",
    "skassists", "skbs", "skdeflections",
    "skfol", "skfopct", "skfow",
    "skgiveaways", "skgoals", "skgwg",
    "skhits", "skinterceptions",
    "skpassattempts", "skpasses", "skpasspct",
    "skpenaltiesdrawn", "skpim", "skpkclearzone",
    "skplusmin", "skpossession",
    "skppg", "sksaucerpasses", "skshg",
    "skshotattempts", "skshotonnetpct", "skshotpct", "skshots",
    "sktakeaways",
    "teamId", "teamSide",
    "toi", "toiseconds",
    "playername", "clientPlatform",
]

PLAYER_STATS_HEADERS = INFO_HEADERS + STAT_HEADERS


def _safe(val, default=""):
    return default if val is None else val


def _ensure_header(ws):
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []

    if not first_row or not any(first_row):
        ws.insert_row(PLAYER_STATS_HEADERS, index=1, value_input_option="USER_ENTERED")
        print(f"[{COG_NAME}] ✅ Header row written ({len(PLAYER_STATS_HEADERS)} columns).")
        return

    if (len(first_row) > 1
            and first_row[0].strip() == "Match ID"
            and first_row[1].strip() == "Username"):
        return  # correct schema

    print(f"[{COG_NAME}] ⚠️  Schema mismatch (col 1='{first_row[0]}').")


def _build_row(mid, pid, p, team_name, our_score, opp_club_id, opp_score, platform):
    toiseconds = _safe(p.get("toiseconds"), 0)
    result     = _calc_result(our_score, opp_score, toiseconds)

    row = [
        str(mid),
        _safe(p.get("playername"), ""),
        str(pid),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        team_name,
        str(our_score),
        str(opp_score),
        str(toiseconds),
        result,
    ]

    for col in STAT_HEADERS:
        if col == "opponentClubId":
            row.append(str(opp_club_id))
        elif col == "opponentScore":
            row.append(str(opp_score))
        elif col == "opponentTeamId":
            row.append(str(opp_club_id))
        elif col == "clientPlatform":
            row.append(str(platform))
        else:
            row.append(_safe(p.get(col), ""))

    return row


def _write_rows_to_sheet(game, config, ws):
    api_clubs = game.get("clubs", {})
    all_cids  = list(api_clubs.keys())
    platform  = config.get("platform", "")
    mid       = str(game["matchId"])
    rows      = []

    # Sum skgoals per team from player data — more accurate than clubs block
    # (clubs score can be wrong in DNF games due to EA API quirk)
    team_goal_totals = {}
    for cid, players in game["players"].items():
        team_goal_totals[cid] = sum(
            int(float(p.get("skgoals", 0))) for p in players.values()
        )

    for cid, players in game["players"].items():
        team_name = (
            config.get("team_ids", {}).get(str(cid))
            or api_clubs.get(cid, {}).get("details", {}).get("name", f"Team {cid}")
        )
        our_score = team_goal_totals.get(cid, 0)
        opp_cid   = next((c for c in all_cids if c != cid), "")
        opp_score = team_goal_totals.get(opp_cid, 0)

        for pid, p in players.items():
            rows.append(_build_row(
                mid, str(pid), p, team_name,
                our_score, opp_cid, opp_score,
                platform
            ))

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


# ════════════════════════════════════════════════════════════
#  PATCHED log_game_data
# ════════════════════════════════════════════════════════════

def _patched_log_game_data(game, config, cached_ids=None):
    """
    Drop-in replacement for utils.log_game_data.
    ALL games write immediately — no hold, no stubs, no dnf.json.
    DNF games queue a notification for DNFManager after writing.
    """
    sh = utils.get_sheet()
    if not sh:
        return "Error"

    try:
        ws  = sh.worksheet("Player Stats")
        mid = str(game["matchId"])

        if cached_ids and mid in cached_ids:
            return "Duplicate"

        _ensure_header(ws)

        # Write all games immediately
        _write_rows_to_sheet(game, config, ws)

        # Queue DNF notification for DNFManager smart menu
        if _is_dnf(game):
            pending = getattr(utils, "_dnf_notify_queue", [])
            pending.append({"matchId": mid, "game": game, "config": config})
            utils._dnf_notify_queue = pending

        # Shadow funnel — redundant, remove once confirmed working
        try:
            utils.log_all_stats_shadow(game, config, sh)
        except Exception:
            pass

        return f"Logged {mid}"

    except Exception as e:
        print(f"[{COG_NAME}] log_game_data error: {e}")
        return f"Error: {e}"


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class StatsLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        utils._dnf_notify_queue      = []
        utils.log_game_data          = _patched_log_game_data
        utils._statslogger_write_rows    = _write_rows_to_sheet
        utils._statslogger_ensure_header = _ensure_header
        utils._statslogger_headers       = PLAYER_STATS_HEADERS

        print(
            f"✅ [{COG_NAME}] v{VERSION} — patched. "
            f"{len(PLAYER_STATS_HEADERS)}-col schema. "
            f"All games write immediately. DNF routed to DNFManager."
        )

    async def cog_load(self):
        await utils.send_log(
            self.bot,
            f"📊 **StatsLogger v{VERSION}** — "
            f"All games write immediately. DNF = smart menu via DNFManager."
        )
        self.bot.loop.create_task(self._drain_dnf_queue())

    async def _drain_dnf_queue(self):
        """Routes DNF notifications to DNFManager.handle_dnf."""
        await self.bot.wait_until_ready()
        import asyncio
        while True:
            queue = getattr(utils, "_dnf_notify_queue", [])
            if queue:
                item = queue.pop(0)
                utils._dnf_notify_queue = queue
                try:
                    dnf_cog = self.bot.get_cog("DNFManager")
                    if dnf_cog:
                        await dnf_cog.handle_dnf(
                            item["matchId"], item["game"], item["config"]
                        )
                    else:
                        await utils.send_log(
                            self.bot,
                            f"⚠️ DNF game `{item['matchId']}` logged — DNFManager not loaded."
                        )
                except Exception as e:
                    print(f"[{COG_NAME}] DNF notify error: {e}")
            await asyncio.sleep(2)


async def setup(bot):
    await bot.add_cog(StatsLogger(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
