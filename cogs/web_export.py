# ============================================================
#  Echelon League Bot — web_export.py
#  Version: 1.1.0
#  Brand new cog — zero existing code modified
#
#  Exports a stats.json file to the bot folder for use by
#  the Echelon League website (index.html).
#
#  Changelog:
#    v1.1.0 — Logo resolution added (logo_overrides.json + NHL keywords)
#             Logo path written into standings/rosters/player_stats/games
#             Fixed GAA: ga / gp  (was incorrectly ga/gp * 60)
#             Normalized EA position strings → LW/RW/C/D/G
#    v1.0.0 — Initial release
# ============================================================

VERSION  = "1.2.0"
COG_NAME = "WebExport"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading...")

import os
import json
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from discord import app_commands

import utils

OUTPUT_FILE    = os.path.join(utils.BASE_DIR, "stats.json")
LOGO_OVERRIDES = os.path.join(utils.BASE_DIR, "logo_overrides.json")
LOGOS_DIR      = os.path.join(utils.BASE_DIR, "logos")
LOGO_WEB_PATH  = "logos/{}.png"
GAME_RESULTS_TAB = "Game Results"

# ── NHL keyword → logo id (mirrors team_logos.py without importing it) ──
_NHL_KEYWORDS = {
    "bruins":"bos","sabres":"buf","red wings":"det","redwings":"det",
    "panthers":"fla","canadiens":"mtl","habs":"mtl","senators":"ott",
    "sens":"ott","lightning":"tb","bolts":"tb","maple leafs":"tor",
    "leafs":"tor","hurricanes":"car","canes":"car",
    "blue jackets":"cbj","jackets":"cbj","devils":"njd",
    "islanders":"nyi","isles":"nyi","rangers":"nyr",
    "flyers":"phi","penguins":"pit","pens":"pit",
    "capitals":"wsh","caps":"wsh","coyotes":"ari","yotes":"ari",
    "blackhawks":"chi","hawks":"chi","avalanche":"col","avs":"col",
    "stars":"dal","wild":"min","predators":"nsh","preds":"nsh",
    "blues":"stl","ducks":"ana","flames":"cgy","oilers":"edm",
    "kings":"lak","sharks":"sjs","kraken":"sea","canucks":"van",
    "golden knights":"vgk","knights":"vgk","jets":"wpg","mammoth":"utah",
    "whalers":"hfd","nordiques":"que","wranglers":"cgy",
}

# ── EA position string normalizer ────────────────────────────
_POS_MAP = {
    "leftwing":"LW","rightwing":"RW","defensemen":"D","defense":"D",
    "centre":"C","center":"C","goalie":"G","leftdefense":"D",
    "rightdefense":"D","lw":"LW","rw":"RW","c":"C","d":"D","g":"G",
    "ld":"D","rd":"D",
}

def _normalize_pos(raw: str) -> str:
    key = str(raw).strip().lower().replace(" ","").replace("_","")
    return _POS_MAP.get(key, raw.strip())

# ── Logo helpers ─────────────────────────────────────────────

def _load_overrides() -> dict:
    try:
        with open(LOGO_OVERRIDES,"r",encoding="utf-8") as f:
            raw = json.load(f)
        return {k.lower().strip(): v for k,v in raw.items()}
    except Exception:
        return {}

def _logo_exists(lid: str) -> bool:
    return os.path.isfile(os.path.join(LOGOS_DIR, f"{lid}.png"))

def _resolve_logo(team_name: str, overrides: dict):
    key = team_name.lower().strip()
    # 1. override exact
    if key in overrides:
        lid = overrides[key]
        if _logo_exists(lid):
            return LOGO_WEB_PATH.format(lid)
    # 2. NHL keyword scan
    for kw, lid in _NHL_KEYWORDS.items():
        if kw in key and _logo_exists(lid):
            return LOGO_WEB_PATH.format(lid)
    return None

def _safe_int(val):
    try: return int(str(val).strip())
    except: return 0

# ── Standings ────────────────────────────────────────────────

def _calc_standings(sh, overrides: dict) -> list:
    try:
        ws = sh.worksheet(GAME_RESULTS_TAB)
        all_rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] standings read error: {e}"); return []
    if len(all_rows) < 2: return []

    teams: dict = {}
    def _ensure(n):
        if n not in teams:
            teams[n] = {"GP":0,"W":0,"L":0,"OTL":0,"GF":0,"GA":0,"PTS":0}

    for row in all_rows[1:]:
        if len(row) < 10: continue
        t1 = str(row[2]).strip(); s1 = _safe_int(row[3]); r1 = str(row[4]).strip().upper()
        t2 = str(row[5]).strip(); s2 = _safe_int(row[6]); r2 = str(row[7]).strip().upper()
        if not t1 or not t2: continue
        _ensure(t1); _ensure(t2)
        teams[t1]["GP"]+=1; teams[t2]["GP"]+=1
        teams[t1]["GF"]+=s1; teams[t1]["GA"]+=s2
        teams[t2]["GF"]+=s2; teams[t2]["GA"]+=s1
        for res,tn in [(r1,t1),(r2,t2)]:
            if res in("W","W-FF","OTW"): teams[tn]["W"]+=1; teams[tn]["PTS"]+=2
            elif res=="OTL":             teams[tn]["OTL"]+=1; teams[tn]["PTS"]+=1
            else:                        teams[tn]["L"]+=1

    if not teams: return []
    srt = sorted(teams.items(), key=lambda x:(x[1]["PTS"],x[1]["W"],x[1]["GF"]-x[1]["GA"]), reverse=True)
    return [{"rank":rank,"team":name,"logo":_resolve_logo(name,overrides),
             "gp":s["GP"],"w":s["W"],"l":s["L"],"otl":s["OTL"],"pts":s["PTS"],
             "gf":s["GF"],"ga":s["GA"],"diff":s["GF"]-s["GA"]}
            for rank,(name,s) in enumerate(srt,1)]

# ── Player Stats ─────────────────────────────────────────────

def _calc_player_stats(sh) -> list:
    stats = {}
    try:
        ws = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] player stats read error: {e}"); return []

    h_idx, h = utils.find_header_row(rows, ["Match ID","Username"])
    if h_idx == -1: return []

    def idx(c):
        try: return h.index(c)
        except: return -1

    # New schema column names with old schema fallbacks
    def idx2(*names):
        for n in names:
            i = idx(n)
            if i != -1: return i
        return -1

    # Load merge map for GP dedup
    try:
        from cogs.lagout import get_merge_map
        sh2 = utils.get_sheet()
        merge_map = get_merge_map(sh2) if sh2 else {}
    except Exception:
        merge_map = {}
    seen_gp = set()

    c_mid  = idx2("Match ID")
    c_user = idx2("Username")
    c_team = idx2("Team Name", "Team ID")
    c_pos  = idx2("position", "Position")
    c_g    = idx2("skgoals", "Goals")
    c_a    = idx2("skassists", "Assists")
    c_pts  = idx2("skgoals", "Points")   # recalc from g+a
    c_hits = idx2("skhits", "Hits")
    c_sv   = idx2("glsaves", "Saves")
    c_ga   = idx2("glga", "Goals Against")
    c_sh   = idx2("skshots", "Shots")
    c_pim  = idx2("skpim", "PIMs")
    c_pm   = idx2("skplusmin", "+/-", "Plus/Minus")

    for r in rows[h_idx+1:]:
        if len(r) <= max(c_user, 0): continue
        n = str(r[c_user]).strip() if c_user != -1 and c_user < len(r) else ""
        if not n or "[MERGED" in n or "[DNF" in n: continue
        tname = str(r[c_team]).strip() if c_team != -1 and c_team < len(r) else ""

        if n not in stats:
            raw_pos = r[c_pos] if c_pos != -1 and c_pos < len(r) else ""
            pos = _normalize_pos(raw_pos)
            stats[n] = {"name":n,"team_id":tname,"position":pos,
                        "gp":0,"g":0,"a":0,"pts":0,"hits":0,
                        "sv":0,"ga":0,"shots":0,"pim":0,"plus_minus":0,
                        "is_goalie": pos=="G" or "goalie" in str(raw_pos).lower()}

        def v(c):
            if c == -1 or c >= len(r): return 0
            try: return int(float(str(r[c]).replace("%","")))
            except: return 0

        s = stats[n]

        # GP dedup for merged games
        raw_mid  = str(r[c_mid]).strip() if c_mid != -1 and c_mid < len(r) else ""
        canon_mid = merge_map.get(raw_mid, raw_mid)
        gp_key = (n, canon_mid)
        if gp_key not in seen_gp:
            seen_gp.add(gp_key)
            s["gp"] += 1

        g_val = v(c_g); a_val = v(c_a)
        s["g"]+=g_val; s["a"]+=a_val; s["pts"]+=g_val+a_val
        s["hits"]+=v(c_hits); s["sv"]+=v(c_sv); s["ga"]+=v(c_ga)
        s["shots"]+=v(c_sh); s["pim"]+=v(c_pim)
        if c_pm != -1 and c_pm < len(r):
            try: s["plus_minus"]+=int(float(str(r[c_pm])))
            except: pass
        if tname: s["team_id"] = tname

    result = []
    for s in stats.values():
        sa=s["sv"]+s["ga"]; s["sa"]=sa
        s["svp"]=round(s["sv"]/sa,3) if sa>0 else 0.000
        s["gaa"]=round(s["ga"]/s["gp"],2) if s["gp"]>0 else 0.00  # ✅ FIXED
        result.append(s)
    return sorted(result, key=lambda x: x["pts"], reverse=True)

# ── Game Results ─────────────────────────────────────────────

def _calc_game_results(sh) -> list:
    try:
        ws = sh.worksheet(GAME_RESULTS_TAB)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] game results read error: {e}"); return []
    if len(rows) < 2: return []
    games = []
    for row in rows[1:]:
        if len(row) < 9: continue
        try:
            games.append({
                "match_id": str(row[0]).strip(), "date": str(row[1]).strip(),
                "team1": str(row[2]).strip(), "score_t1": _safe_int(row[3]),
                "result_t1": str(row[4]).strip(),
                "team2": str(row[5]).strip(), "score_t2": _safe_int(row[6]),
                "result_t2": str(row[7]).strip(),
                "game_type": str(row[9]).strip() if len(row)>9 else "",
                "game_time": str(row[10]).strip() if len(row)>10 else "",
            })
        except: continue
    return games

# ── Rosters ──────────────────────────────────────────────────

def _calc_rosters(sh, config: dict, overrides: dict) -> list:
    team_ids = config.get("team_ids",{})
    rosters  = utils.get_roster_data_from_sheet(config)
    result = []
    for tid, players in rosters.items():
        tname = team_ids.get(tid, f"Team {tid}")
        sorted_p = sorted([{"name":n,"gp":gp} for n,gp in players.items()],
                          key=lambda x: x["gp"], reverse=True)
        result.append({"team_id":tid,"team":tname,
                       "logo":_resolve_logo(tname,overrides),"players":sorted_p})
    return sorted(result, key=lambda x: x["team"])

# ── Master build ─────────────────────────────────────────────

def _build_export(config: dict) -> dict:
    sh = utils.get_sheet()
    if not sh: raise RuntimeError("Could not connect to Google Sheets")

    team_ids  = config.get("team_ids",{})
    overrides = _load_overrides()

    standings    = _calc_standings(sh, overrides)
    player_stats = _calc_player_stats(sh)
    game_results = _calc_game_results(sh)
    rosters      = _calc_rosters(sh, config, overrides)

    # Build logo lookup from resolved standings + rosters
    logo_map = {r["team"]: r["logo"] for r in standings if r.get("logo")}
    for r in rosters:
        if r.get("logo"): logo_map[r["team"]] = r["logo"]

    # Attach team name + logo to player stats
    for p in player_stats:
        tname = team_ids.get(p.get("team_id",""), p.get("team_id","Unknown"))
        p["team"] = tname
        p["logo"] = logo_map.get(tname) or _resolve_logo(tname, overrides)

    # Attach logos to game result rows
    for g in game_results:
        g["logo_t1"] = logo_map.get(g["team1"]) or _resolve_logo(g["team1"], overrides)
        g["logo_t2"] = logo_map.get(g["team2"]) or _resolve_logo(g["team2"], overrides)

    logos_found = sum(1 for r in standings if r.get("logo"))
    print(f"[{COG_NAME}] Logo resolution: {logos_found}/{len(standings)} teams matched")

    return {
        "meta": {"league":"Echelon League",
                 "exported_at":datetime.now(timezone.utc).isoformat(),
                 "version":VERSION},
        "standings":    standings,
        "player_stats": player_stats,
        "game_results": game_results,
        "rosters":      rosters,
    }

# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class WebExport(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print(f"🌐 [{COG_NAME}] Initialized — v{VERSION}")

    async def cog_load(self):
        self._export_loop.start()
        print(f"⏱️  [{COG_NAME}] Auto-export loop started (every 30 min)")

    async def cog_unload(self):
        self._export_loop.cancel()

    async def _do_export(self) -> str:
        loop    = asyncio.get_event_loop()
        payload = await loop.run_in_executor(None, _build_export, self.bot.config)
        def _write():
            with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        await loop.run_in_executor(None, _write)
        ts = payload["meta"]["exported_at"]
        logos = sum(1 for r in payload["standings"] if r.get("logo"))
        return (f"✅ stats.json v{VERSION} — "
                f"{len(payload['standings'])} teams ({logos} logos) | "
                f"{len(payload['player_stats'])} players | "
                f"{len(payload['game_results'])} games | {ts}")

    @tasks.loop(minutes=30)
    async def _export_loop(self):
        try:
            status = await self._do_export()
            print(f"[{COG_NAME}] {status}")
        except Exception as e:
            print(f"[{COG_NAME}] Auto-export error: {e}")

    @_export_loop.before_loop
    async def _before_export(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="exportstats",
                          description="[Admin] Manually export stats.json for the league website.")
    @app_commands.checks.has_permissions(administrator=True)
    async def exportstats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            status = await self._do_export()
            await interaction.followup.send(
                f"🌐 **Web Export Complete**\n`{status}`\n\n"
                f"📁 `stats.json` written to bot folder.\n"
                f"🔄 Auto-exports every 30 minutes.",
                ephemeral=True)
            print(f"[{COG_NAME}] Manual export by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"❌ Export failed: `{e}`", ephemeral=True)
            print(f"[{COG_NAME}] Manual export error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WebExport(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
