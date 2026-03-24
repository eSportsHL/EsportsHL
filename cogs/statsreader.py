# ============================================================
#  Echelon League Bot — statsreader.py
#  Version: 1.0.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Purpose:
#    Patches three utils reader functions at runtime so they
#    read the new 65-column Player Stats schema written by
#    statslogger.py v1.2.0+.
#
#    Patched functions:
#      utils.get_roster_data_from_sheet()
#      utils.get_season_stats_from_sheet()
#      utils.get_detailed_stats()
#
#  New column name mappings (old → new):
#    Team ID      → Team Name
#    Position     → position
#    Goals        → skgoals
#    Assists      → skassists
#    Points       → calculated (skgoals + skassists)
#    Hits         → skhits
#    Saves        → glsaves
#    Goals Against→ glga
#    Shots        → skshots
#    PIMs         → skpim
#    +/-          → skplusmin
#    Interceptions→ skinterceptions
#    Blocked Shots→ skbs
#    Desp. Saves  → gldsaves
#    Takeaways    → sktakeaways
#    Giveaways    → skgiveaways
#    GWG          → skgwg
#    FOW          → skfow
#    FOL          → skfol
#    FO%          → skfopct
#    Pass Att     → skpassattempts
#    Passes       → skpasses
#    Pass%        → skpasspct
#    PPG          → skppg
#    SHG          → skshg
#    Shot Att     → skshotattempts
#    Sauc         → sksaucerpasses
#    Possession   → skpossession
#    TOI          → toiseconds
#    GAA          → calculated (glga / GP)
#    Save %       → calculated (glsaves / (glsaves + glga))
#
#  Stub rows ([DNF-PENDING]) are skipped in all readers.
#
#  Changelog:
#    v1.0.0 — Initial release.
# ============================================================

VERSION  = "1.3.0"
COG_NAME = "StatsReader"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — New schema reader patches")

import utils
from discord.ext import commands

DNF_STUB_TAG = "[DNF-PENDING]"


# ════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ════════════════════════════════════════════════════════════

def _si(row, col):
    """Safe int from row[col]."""
    if col == -1 or col >= len(row):
        return 0
    try:
        return int(float(str(row[col]).replace("%", "")))
    except (ValueError, TypeError):
        return 0


def _sf(row, col):
    """Safe float from row[col]."""
    if col == -1 or col >= len(row):
        return 0.0
    try:
        return float(str(row[col]).replace("%", ""))
    except (ValueError, TypeError):
        return 0.0


def _is_stub(row, col_username):
    """Returns True if this row is a DNF-PENDING stub."""
    if col_username == -1 or col_username >= len(row):
        return False
    return DNF_STUB_TAG in str(row[col_username])


def _pos_category(pos_raw: str) -> str:
    """Map raw EA position string to Forward / Defense / Goalie."""
    p = str(pos_raw).strip().lower()
    if "goalie" in p or "goaltender" in p or p in ("g", "0"):
        return "Goalie"
    if "defense" in p or "defence" in p or p in ("d", "ld", "rd", "def", "defenseman"):
        return "Defense"
    return "Forward"


# ════════════════════════════════════════════════════════════
#  PATCHED get_roster_data_from_sheet
#  Returns {team_name: {player_name: gp}} AND
#          {team_id: {player_name: gp}} merged together
#  so existing cogs that key by team_id still work.
# ════════════════════════════════════════════════════════════

def _patched_get_roster_data_from_sheet(config):
    """
    Returns {team_name: {player_name: gp}}.
    Keyed by team name from the sheet — no empty config ID seeds
    so teams never appear twice.
    Also sets utils._roster_by_name for image_engine positional data.
    """
    rosters = {}

    sh = utils.get_sheet()
    if not sh:
        return rosters

    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Match ID", "Username"])
        if h_idx == -1:
            return rosters

        def idx(col):
            try:    return h.index(col)
            except: return -1

        c_user = idx("Username")
        c_team = idx("Team Name")

        if c_user == -1:
            return rosters

        for r in rows[h_idx + 1:]:
            if len(r) <= c_user:
                continue
            if _is_stub(r, c_user):
                continue

            name  = str(r[c_user]).strip()
            tname = str(r[c_team]).strip() if c_team != -1 and c_team < len(r) else ""
            if not name or not tname:
                continue

            if tname not in rosters:
                rosters[tname] = {}
            rosters[tname][name] = rosters[tname].get(name, 0) + 1

    except Exception as e:
        print(f"[{COG_NAME}] get_roster_data_from_sheet error: {e}")

    return rosters


# ════════════════════════════════════════════════════════════
#  PATCHED get_season_stats_from_sheet
#  Returns {player_name: stat_dict} with all keys the rest
#  of the bot expects, plus extended columns for leaderboard.
# ════════════════════════════════════════════════════════════

def _patched_get_season_stats_from_sheet(config):
    stats = {}
    sh    = utils.get_sheet()
    if not sh:
        return {}

    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Match ID", "Username"])
        if h_idx == -1:
            return {}

        def idx(col):
            try:    return h.index(col)
            except: return -1

        c_user = idx("Username")
        c_team = idx("Team Name")
        c_pos  = idx("position")
        c_res  = idx("Result")

        # Stat columns
        c_g    = idx("skgoals")
        c_a    = idx("skassists")
        c_hits = idx("skhits")
        c_sv   = idx("glsaves")
        c_ga   = idx("glga")
        c_sh   = idx("skshots")
        c_pim  = idx("skpim")
        c_pm   = idx("skplusmin")
        c_int  = idx("skinterceptions")
        c_bs   = idx("skbs")
        c_ds   = idx("gldsaves")
        c_tk   = idx("sktakeaways")
        c_gv   = idx("skgiveaways")
        c_gwg  = idx("skgwg")
        c_fow  = idx("skfow")
        c_fol  = idx("skfol")
        c_fo   = idx("skfopct")
        c_pa   = idx("skpassattempts")
        c_ps   = idx("skpasses")
        c_pp   = idx("skpasspct")
        c_ppg  = idx("skppg")
        c_shg  = idx("skshg")
        c_sa   = idx("skshotattempts")
        c_sauc = idx("sksaucerpasses")
        c_poss = idx("skpossession")
        c_toi  = idx("toiseconds")
        c_def  = idx("skdeflections")
        c_pd   = idx("skpenaltiesdrawn")
        c_mid  = idx("Match ID")

        # Load merge map so merged sessions count as 1 GP
        try:
            from cogs.lagout import get_merge_map
            merge_map = get_merge_map(sh)
        except Exception:
            merge_map = {}

        # Track (player, canonical_match_id) to avoid double GP from merged sessions
        seen_gp = set()

        for r in rows[h_idx + 1:]:
            if len(r) <= c_user or c_user == -1:
                continue
            if _is_stub(r, c_user):
                continue

            name = str(r[c_user]).strip()
            if not name:
                continue

            pos_raw  = str(r[c_pos]).strip() if c_pos != -1 and c_pos < len(r) else "forward"
            pos_cat  = _pos_category(pos_raw)
            tname    = str(r[c_team]).strip() if c_team != -1 and c_team < len(r) else ""
            result   = str(r[c_res]).strip()  if c_res  != -1 and c_res  < len(r) else ""

            # Canonical match ID (remapped if absorbed)
            raw_mid  = str(r[c_mid]).strip() if c_mid != -1 and c_mid < len(r) else ""
            canon_mid = merge_map.get(raw_mid, raw_mid)

            if name not in stats:
                stats[name] = {
                    "GP": 0, "G": 0, "A": 0, "P": 0,
                    "Hits": 0, "Sv": 0, "GA": 0, "S": 0, "PIM": 0, "+/-": 0,
                    "INT": 0, "BS": 0, "DS": 0, "TK": 0, "GV": 0, "GWG": 0,
                    "FOW": 0, "FOL": 0, "FO%": 0.0,
                    "Pass": 0, "PassAtt": 0, "Pass%": 0.0,
                    "PPG": 0, "SHG": 0, "ShotAtt": 0, "Sauc": 0, "Poss": 0,
                    "TOI": 0, "DEF": 0, "PD": 0,
                    "W": 0, "L": 0, "OTW": 0, "OTL": 0,
                    "Main Position": "Goalie" if pos_cat == "Goalie" else "Skater",
                    "Team": tname,
                    "Save % Value": 0.0,
                }

            s = stats[name]
            # Only count GP once per canonical match ID per player
            gp_key = (name, canon_mid)
            if gp_key not in seen_gp:
                seen_gp.add(gp_key)
                s["GP"] += 1

            # Accumulate based on position
            if pos_cat == "Goalie":
                s["Main Position"] = "Goalie"
                s["Sv"]  += _si(r, c_sv)
                s["GA"]  += _si(r, c_ga)
                s["DS"]  += _si(r, c_ds)
            else:
                s["G"]    += _si(r, c_g)
                s["A"]    += _si(r, c_a)
                s["Hits"] += _si(r, c_hits)
                s["S"]    += _si(r, c_sh)
                s["+/-"]  += _si(r, c_pm)
                s["INT"]  += _si(r, c_int)
                s["BS"]   += _si(r, c_bs)
                s["TK"]   += _si(r, c_tk)
                s["GV"]   += _si(r, c_gv)
                s["GWG"]  += _si(r, c_gwg)
                s["FOW"]  += _si(r, c_fow)
                s["FOL"]  += _si(r, c_fol)
                s["Pass"] += _si(r, c_ps)
                s["PassAtt"] += _si(r, c_pa)
                s["PPG"]  += _si(r, c_ppg)
                s["SHG"]  += _si(r, c_shg)
                s["ShotAtt"] += _si(r, c_sa)
                s["Sauc"] += _si(r, c_sauc)
                s["Poss"] += _si(r, c_poss)
                s["DEF"]  += _si(r, c_def)
                s["PD"]   += _si(r, c_pd)

            s["PIM"] += _si(r, c_pim)
            s["TOI"] += _si(r, c_toi)

            # Win/loss tracking
            if result in ("W", "Mercy W"):     s["W"]   += 1
            elif result in ("L", "Mercy L"):   s["L"]   += 1
            elif result == "OTW":              s["OTW"] += 1
            elif result == "OTL":              s["OTL"] += 1

        # Derived stats
        for s in stats.values():
            s["P"] = s["G"] + s["A"]
            total  = s["Sv"] + s["GA"]
            s["Save % Value"] = s["Sv"] / total if total > 0 else 0.0
            fot = s["FOW"] + s["FOL"]
            s["FO%"] = round(s["FOW"] / fot * 100, 1) if fot > 0 else 0.0
            pat = s["PassAtt"]
            s["Pass%"] = round(s["Pass"] / pat * 100, 1) if pat > 0 else 0.0

    except Exception as e:
        print(f"[{COG_NAME}] get_season_stats_from_sheet error: {e}")

    return stats


# ════════════════════════════════════════════════════════════
#  PATCHED get_detailed_stats
#  Returns the split stat dict used by /card
# ════════════════════════════════════════════════════════════

def _patched_get_detailed_stats(target, is_team=False):
    sh     = utils.get_sheet()
    target = str(target).strip().lower()

    data = {
        "Total":   {"GP":0,"G":0,"A":0,"P":0,"Hits":0,"Sv":0,"GA":0,"S":0,
                    "PIM":0,"+/-":0,"INT":0,"BS":0,"DS":0,"TK":0,"GV":0,
                    "Main Position": "Skater"},
        "Forward": {"GP":0,"G":0,"A":0,"P":0,"Hits":0,"S":0,"PIM":0,"+/-":0,
                    "INT":0,"BS":0,"TK":0,"GV":0},
        "Defense": {"GP":0,"G":0,"A":0,"P":0,"Hits":0,"S":0,"PIM":0,"+/-":0,
                    "INT":0,"BS":0,"TK":0,"GV":0},
        "Goalie":  {"GP":0,"Sv":0,"GA":0,"SA":0,"A":0,"P":0,"PIM":0,"DS":0},
    }

    if not sh:
        return data

    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Match ID", "Username"])
        if h_idx == -1:
            return data

        def idx(col):
            try:    return h.index(col)
            except: return -1

        c_user = idx("Username")
        c_pos  = idx("position")
        c_g    = idx("skgoals");    c_a   = idx("skassists")
        c_hits = idx("skhits");     c_sh  = idx("skshots")
        c_pim  = idx("skpim");      c_pm  = idx("skplusmin")
        c_sv   = idx("glsaves");    c_ga  = idx("glga")
        c_int  = idx("skinterceptions")
        c_bs   = idx("skbs");       c_ds  = idx("gldsaves")
        c_tk   = idx("sktakeaways"); c_gv = idx("skgiveaways")

        c_mid = idx("Match ID")

        # Load merge map for GP dedup
        try:
            from cogs.lagout import get_merge_map
            merge_map = get_merge_map(sh)
        except Exception:
            merge_map = {}
        seen_gp = set()

        skater_games = 0
        goalie_games = 0

        for r in rows[h_idx + 1:]:
            if len(r) <= c_user or c_user == -1:
                continue
            if _is_stub(r, c_user):
                continue

            name = str(r[c_user]).strip().lower()
            if name != target:
                continue

            pos_raw  = str(r[c_pos]).strip() if c_pos != -1 and c_pos < len(r) else "forward"
            pos_cat  = _pos_category(pos_raw)

            # GP dedup for merged games
            raw_mid   = str(r[c_mid]).strip() if c_mid != -1 and c_mid < len(r) else ""
            canon_mid = merge_map.get(raw_mid, raw_mid)
            gp_key    = (name, canon_mid)
            count_gp  = gp_key not in seen_gp
            if count_gp:
                seen_gp.add(gp_key)
                if pos_cat == "Goalie":
                    goalie_games += 1
                else:
                    skater_games += 1

            # Total
            t = data["Total"]
            if count_gp:
                t["GP"] += 1
            t["G"]    += _si(r, c_g)
            t["A"]    += _si(r, c_a)
            t["Hits"] += _si(r, c_hits)
            t["Sv"]   += _si(r, c_sv)
            t["GA"]   += _si(r, c_ga)
            t["S"]    += _si(r, c_sh)
            t["PIM"]  += _si(r, c_pim)
            t["+/-"]  += _si(r, c_pm)
            t["INT"]  += _si(r, c_int)
            t["BS"]   += _si(r, c_bs)
            t["DS"]   += _si(r, c_ds)
            t["TK"]   += _si(r, c_tk)
            t["GV"]   += _si(r, c_gv)

            # Positional
            p = data[pos_cat]
            p["GP"] += 1
            if pos_cat == "Goalie":
                sv2 = _si(r, c_sv); ga2 = _si(r, c_ga)
                p["Sv"]  += sv2
                p["GA"]  += ga2
                p["SA"]  += sv2 + ga2
                p["A"]   += _si(r, c_a)
                p["P"]   += _si(r, c_a)   # goalies rarely score goals
                p["PIM"] += _si(r, c_pim)
                p["DS"]  += _si(r, c_ds)
            else:
                p["G"]    += _si(r, c_g)
                p["A"]    += _si(r, c_a)
                p["P"]    += _si(r, c_g) + _si(r, c_a)
                p["Hits"] += _si(r, c_hits)
                p["S"]    += _si(r, c_sh)
                p["PIM"]  += _si(r, c_pim)
                p["+/-"]  += _si(r, c_pm)
                p["INT"]  += _si(r, c_int)
                p["BS"]   += _si(r, c_bs)
                p["TK"]   += _si(r, c_tk)
                p["GV"]   += _si(r, c_gv)

        t = data["Total"]
        t["P"]           = t["G"] + t["A"]
        t["Main Position"] = "Goalie" if goalie_games > skater_games else "Skater"

    except Exception as e:
        print(f"[{COG_NAME}] get_detailed_stats error: {e}")

    return data


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class StatsReader(commands.Cog):
    """
    Patches utils reader functions to read the new 65-column
    Player Stats schema written by statslogger.py v1.2.0+.
    No existing files modified.
    """

    def __init__(self, bot):
        self.bot = bot

        utils.get_roster_data_from_sheet  = _patched_get_roster_data_from_sheet
        utils.get_season_stats_from_sheet = _patched_get_season_stats_from_sheet
        utils.get_detailed_stats          = _patched_get_detailed_stats

        print(
            f"✅ [{COG_NAME}] v{VERSION} — 3 reader functions patched for new schema."
        )

    async def cog_load(self):
        await utils.send_log(
            self.bot,
            f"📖 **StatsReader v{VERSION}** loaded — "
            f"Reader functions patched for new 65-column schema."
        )


async def setup(bot):
    await bot.add_cog(StatsReader(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
