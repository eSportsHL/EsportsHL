# ============================================================
#  OS4 League Bot — game_results.py
#  Version: 2.7.3
#  Changelog:
#    v2.7.3 - BUGFIX: Local image functions generate_game_results_image
#             and generate_player_match_card now use the gold (#C9A84C)
#             brand palette matching image_engine.py. Previously they
#             used the old blue (#58a6ff) for team/section headers,
#             producing visually inconsistent output vs every other
#             generated image in the bot.
#    v2.7.2 - Multi-page season results tracking (past_ids / current_id)
#    v2.7.1 - _refresh_season_image handles list of buffers (multi-page)
#    v1.7.0 - Route generate_season_summary_image through utils
#    v1.6.0 - Blocking sheet calls in run_in_executor
#    v1.5.0 - Merge-aware _build_game_rows
#    v1.4.1 - Team name resolution majority vote per team_id
# ============================================================

VERSION = "2.7.3"
COG_NAME = "GameResults"

import io
import asyncio
from collections import Counter
import discord
from discord.ext import commands, tasks
from discord import app_commands
import utils
from utils import get_base_image_context

print(f"📦 [{COG_NAME}] Cog v{VERSION} loaded — gold brand palette + blocking calls in executor")

# ════════════════════════════════════════════════════════════
#  BRANDING HELPERS
# ════════════════════════════════════════════════════════════

def _get_league_name() -> str:
    try:    return utils.get_league_name()
    except: return utils.load_config().get("league_name", "League")

def _get_bot_name() -> str:
    try:    return utils.get_bot_name()
    except: return utils.load_config().get("bot_name", "Stats Bot")

# ════════════════════════════════════════════════════════════
#  SHARED COLORS  (updated to gold brand palette v2.7.3)
# ════════════════════════════════════════════════════════════

C = {
    "win":     "#3fb950",
    "loss":    "#f85149",
    "dnf":     "#f0883e",
    "score":   "#ffffff",
    "grey":    "#aaaaaa",
    "dark":    "#010409",
    "divider": "#30363d",
    "home":    "#C9A84C",   # ← v2.7.3: was #58a6ff (old blue), now gold to match brand
    "away":    "#f85149",
}

# Gold accent used for pill tops / header bars (matches image_engine B["accent"])
_ACCENT  = "#C9A84C"
_ACCENT2 = "#8B6914"


def _result_color(result: str) -> str:
    if result in ("W", "OTW"):  return C["win"]
    if result in ("L", "OTL"):  return C["loss"]
    return C["dnf"]


# ════════════════════════════════════════════════════════════
#  TEAM NAME RESOLVER  v2
# ════════════════════════════════════════════════════════════

def _resolve_team_names(sh, match_data: dict, config: dict) -> dict:
    resolved = {str(k): str(v) for k, v in config.get("team_ids", {}).items()}

    all_tids = set()
    for data in match_data.values():
        all_tids.update(data["teams"].keys())

    missing = {tid for tid in all_tids if tid not in resolved}

    if missing:
        player_to_tid = {}
        for data in match_data.values():
            for tid, team in data["teams"].items():
                for p in team["players"]:
                    player_to_tid[p["username"]] = tid

        votes: dict[str, Counter] = {tid: Counter() for tid in missing}

        for tab in ("Master Totals Skaters", "Master Totals Goalies"):
            try:
                ws     = sh.worksheet(tab)
                rows   = ws.get_all_values()
                if not rows:
                    continue
                header = rows[0]
                c_name = header.index("Player Name")
                c_team = header.index("Team Name")
            except Exception:
                continue

            for row in rows[1:]:
                if len(row) <= max(c_name, c_team):
                    continue
                pname = row[c_name].strip()
                tname = row[c_team].strip()
                if not pname or not tname:
                    continue
                tid = player_to_tid.get(pname)
                if tid and tid in votes:
                    votes[tid][tname] += 1

        for tid, counter in votes.items():
            if counter:
                resolved[tid] = counter.most_common(1)[0][0]

    for data in match_data.values():
        tids = list(data["teams"].keys())
        if len(tids) == 2:
            n1 = resolved.get(tids[0], tids[0])
            n2 = resolved.get(tids[1], tids[1])
            if n1 == n2:
                resolved[tids[1]] = f"Team {tids[1]}"

    for tid in all_tids:
        if tid not in resolved:
            resolved[tid] = tid

    return resolved


# ════════════════════════════════════════════════════════════
#  INDIVIDUAL GAME IMAGE  (gold palette — v2.7.3)
# ════════════════════════════════════════════════════════════

def generate_game_results_image(game: dict, team_names: dict) -> io.BytesIO:
    t1_name = team_names.get(game["team1_id"], game["team1_id"]).upper()
    t2_name = team_names.get(game["team2_id"], game["team2_id"]).upper()

    t1_players = [p for p in game["all_players"] if p["team_id"] == game["team1_id"]]
    t2_players = [p for p in game["all_players"] if p["team_id"] == game["team2_id"]]

    WIDTH, HEIGHT = 1600, 4000
    img, draw, fonts = get_base_image_context(WIDTH, HEIGHT)

    # Header
    draw.rectangle((0, 0, WIDTH, 200), fill=C["dark"])
    draw.rectangle((0, 0, 6, 200), fill=_ACCENT)        # ← gold left bar
    draw.text((50, 30), t1_name[:20], font=fonts["team"], fill=C["home"])
    t2w = draw.textlength(t2_name[:20], font=fonts["team"])
    draw.text((WIDTH - 50 - t2w, 30), t2_name[:20], font=fonts["team"], fill=C["away"])

    stxt = f"{game['score_t1']}   -   {game['score_t2']}"
    sw   = draw.textlength(stxt, font=fonts["score"])
    draw.text(((WIDTH - sw) / 2, 20), stxt, font=fonts["score"], fill=C["score"])

    r1c = _result_color(game["result_t1"])
    r2c = _result_color(game["result_t2"])
    draw.text((50, 140), game["result_t1"], font=fonts["header"], fill=r1c)
    r2w = draw.textlength(game["result_t2"], font=fonts["header"])
    draw.text((WIDTH - 50 - r2w, 140), game["result_t2"], font=fonts["header"], fill=r2c)

    type_label = {"REG": "Regulation", "OT": "Overtime", "DNF": "DNF / Forfeit"}.get(game["game_type"], "")
    meta = f"Match {game['match_id']}  •  {game['date']}  •  {game['game_minutes']} min  •  {type_label}"
    mw   = draw.textlength(meta, font=fonts["small"])
    draw.text(((WIDTH - mw) / 2, 170), meta, font=fonts["small"], fill=C["grey"])
    draw.rectangle((0, 198, WIDTH, 200), fill=_ACCENT)  # ← gold bottom rule

    y = 210

    def draw_team_block(players, team_name, team_color, start_y):
        cy      = start_y
        skaters = sorted([p for p in players if "goalie" not in p["position"].lower()],
                         key=lambda p: p["points"], reverse=True)
        goalies = [p for p in players if "goalie" in p["position"].lower()]

        draw.rectangle((0, cy, WIDTH, cy + 55), fill=C["dark"])
        draw.rectangle((0, cy, 6, cy + 55), fill=team_color)
        draw.text((50, cy + 10), f"{team_name} — SKATERS", font=fonts["h2"], fill=team_color)
        cy += 65

        sk_xs = [50, 420, 560, 660, 760, 900, 1050]
        for i, h in enumerate(["Player", "Pos", "G", "A", "PTS", "Hits", "+/-"]):
            draw.text((sk_xs[i], cy), h, font=fonts["header"], fill=C["grey"])
        cy += 45
        draw.line((50, cy, WIDTH - 50, cy), fill=C["divider"], width=2)
        cy += 10

        for p in skaters:
            pm  = p.get("plus_minus", 0)
            pmc = C["win"] if pm > 0 else (C["loss"] if pm < 0 else C["grey"])
            for i, v in enumerate([p["username"][:20], p["position"], str(p["goals"]),
                                    str(p["assists"]), str(p["points"]), str(p["hits"]), str(pm)]):
                draw.text((sk_xs[i], cy), v, font=fonts["row"],
                          fill=pmc if i == 6 else (C["score"] if i == 0 else C["grey"]))
            cy += 42

        cy += 20

        if goalies:
            draw.rectangle((0, cy, WIDTH, cy + 55), fill=C["dark"])
            draw.rectangle((0, cy, 6, cy + 55), fill=team_color)
            draw.text((50, cy + 10), f"{team_name} — GOALIES", font=fonts["h2"], fill=team_color)
            cy += 65

            gl_xs = [50, 420, 560, 660, 780, 960]
            for i, h in enumerate(["Player", "SA", "SV", "GA", "SV%", "TOI"]):
                draw.text((gl_xs[i], cy), h, font=fonts["header"], fill=C["grey"])
            cy += 45
            draw.line((50, cy, WIDTH - 50, cy), fill=C["divider"], width=2)
            cy += 10

            for p in goalies:
                sv, ga = p["saves"], p["ga"]
                sa     = sv + ga
                svp    = f"{(sv/sa):.3f}" if sa > 0 else "0.000"
                toi    = f"{p['toiseconds']//60}:{p['toiseconds']%60:02d}"
                for i, v in enumerate([p["username"][:20], str(sa), str(sv), str(ga), svp, toi]):
                    draw.text((gl_xs[i], cy), v, font=fonts["row"],
                              fill=C["score"] if i == 0 else C["grey"])
                cy += 42

        cy += 30
        return cy

    y = draw_team_block(t1_players, t1_name, C["home"], y)
    draw.line((50, y, WIDTH - 50, y), fill=C["divider"], width=3)
    y += 20
    y = draw_team_block(t2_players, t2_name, C["away"], y)

    ft = f"{_get_bot_name()}  •  Game Results v{VERSION}"
    fw = draw.textlength(ft, font=fonts["small"])
    draw.text(((WIDTH - fw) / 2, y + 10), ft, font=fonts["small"], fill=C["grey"])
    y += 55

    img = img.crop((0, 0, WIDTH, y))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  SEASON SUMMARY IMAGE
# ════════════════════════════════════════════════════════════

def generate_season_summary_image(summary: list, team_names: dict) -> io.BytesIO:
    WIDTH  = 1500
    ROW_H  = 52
    HDR_H  = 160
    COL_H  = 55
    HEIGHT = HDR_H + COL_H + (len(summary) * ROW_H) + 60

    img, draw, fonts = get_base_image_context(WIDTH, HEIGHT)

    draw.rectangle((0, 0, WIDTH, HDR_H), fill=C["dark"])
    draw.rectangle((0, 0, 6, HDR_H), fill=_ACCENT)
    draw.text((50, 18), _get_league_name().upper() + " SEASON RESULTS", font=fonts["title"], fill=C["score"])
    reg = sum(1 for g in summary if g["game_type"] == "REG")
    ot  = sum(1 for g in summary if g["game_type"] == "OT")
    dnf = sum(1 for g in summary if g["game_type"] == "DNF")
    draw.text((50, 110), f"{len(summary)} Games  •  {reg} Regulation  •  {ot} Overtime  •  {dnf} DNF",
              font=fonts["small"], fill=C["grey"])
    draw.line((50, HDR_H - 8, WIDTH - 50, HDR_H - 8), fill=_ACCENT2, width=2)

    NUM_X    = 30
    T1_X     = 85
    R1_X     = 690
    SCORE_CX = 760
    R2_X     = 830
    T2_X     = 1460

    y = HDR_H
    draw.text((NUM_X, y + 8), "#",        font=fonts["header"], fill=C["grey"])
    draw.text((T1_X,  y + 8), "TEAM",     font=fonts["header"], fill=_ACCENT)
    shw = draw.textlength("SCORE", font=fonts["header"])
    draw.text((SCORE_CX - shw / 2, y + 8), "SCORE", font=fonts["header"], fill=_ACCENT)
    ohw = draw.textlength("OPPONENT", font=fonts["header"])
    draw.text((T2_X - ohw, y + 8), "OPPONENT", font=fonts["header"], fill=_ACCENT)
    y += COL_H
    draw.line((50, y, WIDTH - 50, y), fill=_ACCENT2, width=2)
    y += 6

    for idx, g in enumerate(summary):
        t1  = team_names.get(g["team1_id"], g["team1_id"])
        t2  = team_names.get(g["team2_id"], g["team2_id"])
        r1c = _result_color(g["result_t1"])
        r2c = _result_color(g["result_t2"])

        draw.rectangle((0, y, WIDTH, y + ROW_H),
                       fill="#0d1117" if idx % 2 == 0 else "#161b22")

        draw.text((NUM_X, y + 12), str(idx + 1), font=fonts["row"], fill=C["grey"])
        draw.text((T1_X,  y + 12), t1[:24],      font=fonts["row"], fill=r1c)

        r1w = draw.textlength(g["result_t1"], font=fonts["row"])
        draw.text((R1_X - r1w, y + 12), g["result_t1"], font=fonts["row"], fill=r1c)

        score_str = f"{g['score_t1']}  -  {g['score_t2']}"
        scw = draw.textlength(score_str, font=fonts["header"])
        draw.text((SCORE_CX - scw / 2, y + 10), score_str, font=fonts["header"], fill=C["score"])

        draw.text((R2_X, y + 12), g["result_t2"], font=fonts["row"], fill=r2c)

        t2w = draw.textlength(t2[:24], font=fonts["row"])
        draw.text((T2_X - t2w, y + 12), t2[:24], font=fonts["row"], fill=r2c)

        y += ROW_H
        draw.line((50, y, WIDTH - 50, y), fill=C["divider"], width=1)

    y += 12
    ft = f"{_get_bot_name()}  •  Season Results v{VERSION}  •  Auto-updates on new matches"
    fw = draw.textlength(ft, font=fonts["small"])
    draw.text(((WIDTH - fw) / 2, y), ft, font=fonts["small"], fill=C["grey"])
    y += 38

    img = img.crop((0, 0, WIDTH, y))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  DATA HELPERS
# ════════════════════════════════════════════════════════════

REGULATION_SECONDS = 3600


def _classify_game(toiseconds):
    if toiseconds < REGULATION_SECONDS:  return "DNF"
    if toiseconds == REGULATION_SECONDS: return "REG"
    return "OT"


def _determine_result(our, opp, game_type):
    won = our > opp
    if game_type == "OT":  return "OTW" if won else "OTL"
    if game_type == "DNF": return "W-FF" if won else "L-FF"
    return "W" if won else "L"


def _get_goalie_toi(players):
    gtoi = [p["toiseconds"] for p in players
            if "goalie" in p["position"].lower() and p["toiseconds"] > 0]
    if gtoi: return max(gtoi)
    atoi = [p["toiseconds"] for p in players if p["toiseconds"] > 0]
    return max(atoi) if atoi else 0


_STUB_NOTE = "[MERGED - DO NOT DELETE]"


def _build_game_rows(sh, config: dict = None):
    try:
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[{COG_NAME}] Sheet read error: {e}")
        return [], {}

    if not rows:
        return [], {}

    header_idx, header = 0, []
    for i, row in enumerate(rows):
        if "Match ID" in row or "matchid" in [c.lower() for c in row]:
            header_idx, header = i, [c.strip() for c in row]
            break
    if not header:
        header = [c.strip() for c in rows[0]]

    def col(n):
        try:    return header.index(n)
        except: return -1

    c_mid  = col("Match ID"); c_date = col("Date")
    c_tid  = col("Team Name") if col("Team Name") != -1 else col("Team ID")
    c_toi  = col("toiseconds") if col("toiseconds") != -1 else col("TOI Seconds") if col("TOI Seconds") != -1 else col("TOI")
    c_g    = col("skgoals")    if col("skgoals")    != -1 else col("Goals")
    c_sv   = col("glsaves")    if col("glsaves")    != -1 else col("Saves")
    c_ga   = col("glga")       if col("glga")       != -1 else col("Goals Against")
    c_usr  = col("Username")
    c_pos  = col("position")   if col("position")   != -1 else col("Position")
    c_ast  = col("skassists")  if col("skassists")  != -1 else col("Assists")
    c_pts  = col("skgoals")    if col("skgoals")    != -1 else col("Points")
    c_hits = col("skhits")     if col("skhits")     != -1 else col("Hits")
    c_pm   = col("skplusmin")  if col("skplusmin")  != -1 else col("+/-")
    c_score= col("Score")

    try:
        try:
            from cogs.lagout import get_merge_map
        except ImportError:
            from cogs.mergegames import get_merge_map
        merge_map = get_merge_map(sh)
    except Exception:
        merge_map = {}

    if merge_map:
        print(f"[{COG_NAME}] Merge map loaded: {len(merge_map)} absorbed ID(s) → primary IDs")

    match_data = {}
    for row in rows[header_idx + 1:]:
        if not row or c_mid == -1 or c_mid >= len(row): continue
        raw_mid = str(row[c_mid]).strip()
        if not raw_mid: continue

        username_val = row[c_usr].strip() if c_usr != -1 and c_usr < len(row) else ""
        if _STUB_NOTE in username_val or "[DNF-PENDING]" in username_val:
            continue

        mid  = merge_map.get(raw_mid, raw_mid)
        tid  = str(row[c_tid]).strip() if c_tid != -1 and c_tid < len(row) else "?"
        date = row[c_date].strip()     if c_date != -1 and c_date < len(row) else ""

        def si(c):
            if c == -1 or c >= len(row): return 0
            try:    return int(float(str(row[c]).replace(",", "")))
            except: return 0

        if mid not in match_data: match_data[mid] = {"date": date, "teams": {}}
        if tid not in match_data[mid]["teams"]:
            match_data[mid]["teams"][tid] = {"score": 0, "players": [], "seen_sessions": set()}

        if raw_mid not in match_data[mid]["teams"][tid]["seen_sessions"]:
            match_data[mid]["teams"][tid]["seen_sessions"].add(raw_mid)
            session_score = si(c_score) if c_score != -1 else 0
            match_data[mid]["teams"][tid]["score"] += session_score if session_score > 0 else si(c_g)

        match_data[mid]["teams"][tid]["players"].append({
            "username":   row[c_usr].strip() if c_usr != -1 and c_usr < len(row) else "?",
            "position":   row[c_pos].strip() if c_pos != -1 and c_pos < len(row) else "",
            "goals":      si(c_g),   "assists":    si(c_ast),
            "points":     si(c_pts), "hits":       si(c_hits),
            "saves":      si(c_sv),  "ga":         si(c_ga),
            "toiseconds": si(c_toi), "team_id":    tid,
            "plus_minus": si(c_pm),
        })

    for data in match_data.values():
        for tid, team in data["teams"].items():
            seen = {}
            for p in team["players"]:
                key = p["username"]
                if key not in seen:
                    seen[key] = dict(p)
                else:
                    for stat in ("goals","assists","points","hits","saves","ga","toiseconds","plus_minus","shots"):
                        seen[key][stat] = seen[key].get(stat, 0) + p.get(stat, 0)
            team["players"] = list(seen.values())

    team_names = _resolve_team_names(sh, match_data, config or {})

    summary = []
    for mid, data in match_data.items():
        teams = data["teams"]
        if len(teams) < 2: continue
        t_ids        = list(teams.keys())
        t1_id, t2_id = t_ids[0], t_ids[1]
        t1, t2       = teams[t1_id], teams[t2_id]
        all_p        = t1["players"] + t2["players"]
        toi          = _get_goalie_toi(all_p)
        gt           = _classify_game(toi)
        summary.append({
            "match_id":     mid,            "date":         data["date"],
            "team1_id":     t1_id,          "team2_id":     t2_id,
            "score_t1":     t1["score"],    "score_t2":     t2["score"],
            "result_t1":    _determine_result(t1["score"], t2["score"], gt),
            "result_t2":    _determine_result(t2["score"], t1["score"], gt),
            "game_type":    gt,             "game_minutes": round(toi / 60, 1),
            "toiseconds":   toi,            "all_players":  all_p,
        })

    summary.sort(key=lambda x: x["match_id"], reverse=True)
    return summary, team_names


def _write_results_tab(sh, summary_rows, team_names):
    TAB = "Game Results"
    try:
        try:    ws = sh.worksheet(TAB); ws.clear()
        except: ws = sh.add_worksheet(title=TAB, rows=500, cols=12)
        ws.append_row(["Match ID","Date","Team 1","Score","Result",
                        "Team 2","Score","Result","Final Score","Game Type","Game Time (min)"],
                      value_input_option="USER_ENTERED")
        rows_out = []
        for g in summary_rows:
            rows_out.append([
                g["match_id"], g["date"],
                team_names.get(g["team1_id"], g["team1_id"]), g["score_t1"], g["result_t1"],
                team_names.get(g["team2_id"], g["team2_id"]), g["score_t2"], g["result_t2"],
                f"{g['score_t1']} - {g['score_t2']}", g["game_type"], g["game_minutes"],
            ])
        if rows_out: ws.append_rows(rows_out, value_input_option="USER_ENTERED")
        return len(rows_out), TAB
    except Exception as e:
        print(f"[{COG_NAME}] Write error: {e}")
        return 0, TAB


# ════════════════════════════════════════════════════════════
#  PLAYER MATCH CARD IMAGE  (gold palette — v2.7.3)
# ════════════════════════════════════════════════════════════

def generate_player_match_card(player: dict, match_id: str, team_name: str) -> io.BytesIO:
    """Branded image card showing all stats for one player in one game."""
    WIDTH, HEIGHT = 900, 480
    img, draw, fonts = get_base_image_context(WIDTH, HEIGHT)

    is_goalie = "goalie" in str(player.get("position","")).lower() or player.get("saves", 0) > 0
    accent    = _ACCENT   # ← v2.7.3: was #FFD700 for goalie / #58a6ff for skater; now unified gold

    # Header bar
    draw.rectangle((0, 0, WIDTH, 120), fill="#010409")
    draw.rectangle((0, 0, 6, 120), fill=accent)
    draw.text((24, 10), player["username"][:24], font=fonts["h1"], fill="white")
    pos_str = "GOALIE" if is_goalie else str(player.get("position","")).upper()
    sub = f"{team_name}  •  {pos_str}  •  Match {match_id}"
    draw.text((26, 88), sub[:60], font=fonts["small"], fill="#8b949e")
    draw.rectangle((0, 118, WIDTH, 120), fill=accent)

    toi_raw = player.get("toiseconds", 0)
    try: toi_raw = int(toi_raw)
    except: toi_raw = 0
    tois = f"{toi_raw//60}:{toi_raw%60:02d}"

    if is_goalie:
        sv  = player.get("saves", 0)
        ga  = player.get("ga", 0)
        sa  = sv + ga
        svp = f"{sv/sa:.3f}" if sa > 0 else "0.000"
        pills = [("SA", sa), ("SV", sv), ("GA", ga), ("SV%", svp), ("TOI", tois)]
    else:
        pm = player.get("plus_minus", 0)
        pills = [
            ("G",    player.get("goals", 0)),
            ("A",    player.get("assists", 0)),
            ("PTS",  player.get("points", 0)),
            ("+/-",  pm),
            ("HITS", player.get("hits", 0)),
            ("S",    player.get("shots", 0)),
            ("TOI",  tois),
        ]

    pill_w = (WIDTH - 60) // len(pills)
    px = 30 + pill_w // 2

    for lbl, val in pills:
        if lbl == "+/-":
            try:
                v   = int(val)
                col = "#3fb950" if v > 0 else ("#f85149" if v < 0 else "#aaaaaa")
            except: col = "#aaaaaa"
        elif lbl in ("PTS", "SV%", "SV"):
            col = "#3fb950"
        else:
            col = "white"

        bx1, bx2 = px - pill_w//2 + 6, px + pill_w//2 - 6
        draw.rectangle((bx1, 140, bx2, 400), fill="#161b22")
        draw.rectangle((bx1, 140, bx2, 143), fill=accent)
        lw = draw.textlength(str(lbl), font=fonts["small"])
        draw.text((px - lw/2, 152), str(lbl), font=fonts["small"], fill="#8b949e")
        vw = draw.textlength(str(val), font=fonts["val"])
        draw.text((px - vw/2, 185), str(val), font=fonts["val"], fill=col)
        px += pill_w

    draw.rectangle((0, HEIGHT - 36, WIDTH, HEIGHT), fill="#010409")
    draw.rectangle((0, HEIGHT - 38, WIDTH, HEIGHT - 36), fill=_ACCENT2)
    ft = f"{_get_bot_name()}  •  Game Results v{VERSION}"
    fw = draw.textlength(ft, font=fonts["small"])
    draw.text(((WIDTH - fw)/2, HEIGHT - 26), ft, font=fonts["small"], fill="#8b949e")

    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  DISCORD UI
# ════════════════════════════════════════════════════════════

class PlayerSelect(discord.ui.Select):
    def __init__(self, players, match_id, team_names):
        self.players, self.team_names, self.match_id = players, team_names, match_id
        options, seen = [], set()
        for p in players[:25]:
            if p["username"] in seen: continue
            seen.add(p["username"])
            options.append(discord.SelectOption(
                label=f"{p['username']} ({p['position']})"[:100],
                description=team_names.get(p["team_id"], p["team_id"])[:100],
                value=p["username"]
            ))
        super().__init__(placeholder=f"👤 Player stats — Match {match_id}...",
                         min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        player = next((p for p in self.players if p["username"] == self.values[0]), None)
        if not player:
            return await interaction.followup.send("❌ Player not found.", ephemeral=True)
        t_name = self.team_names.get(player["team_id"], player["team_id"])
        try:
            buf  = generate_player_match_card(player, self.match_id, t_name)
            file = discord.File(buf, filename="player_card.png")
            await interaction.followup.send(file=file, ephemeral=True)
        except Exception as e:
            print(f"[{COG_NAME}] Player card error: {e}")
            g = player.get("goals",0); a = player.get("assists",0); pts = player.get("points",0)
            await interaction.followup.send(
                f"**{player['username']}** — {t_name}" + chr(10) + f"G:{g}  A:{a}  PTS:{pts}",
                ephemeral=True
            )


class PlayerView(discord.ui.View):
    def __init__(self, players, match_id, team_names):
        super().__init__(timeout=120)
        self.add_item(PlayerSelect(players, match_id, team_names))


class GameSelect(discord.ui.Select):
    def __init__(self, summary, team_names):
        self.summary, self.team_names = summary, team_names
        options = []
        for g in summary[:25]:
            t1  = team_names.get(g["team1_id"], g["team1_id"])
            t2  = team_names.get(g["team2_id"], g["team2_id"])
            tag = " (OT)" if g["game_type"]=="OT" else (" (DNF)" if g["game_type"]=="DNF" else "")
            options.append(discord.SelectOption(
                label=f"{t1} {g['score_t1']} - {g['score_t2']} {t2}{tag}"[:100],
                description=f"Match {g['match_id']} • {g['date']} • {g['game_minutes']} min"[:100],
                value=g["match_id"]
            ))
        super().__init__(placeholder="🎮 Select a game...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        game = next((g for g in self.summary if g["match_id"] == self.values[0]), None)
        if not game:
            return await interaction.followup.send("❌ Game not found.", ephemeral=True)

        tn         = self.team_names
        t1         = tn.get(game["team1_id"], game["team1_id"])
        t2         = tn.get(game["team2_id"], game["team2_id"])
        type_label = {"REG":"Regulation","OT":"Overtime","DNF":"DNF / Forfeit"}[game["game_type"]]
        colour     = (discord.Color.green()  if game["result_t1"] in ("W","OTW") else
                      discord.Color.orange() if game["game_type"] == "DNF" else
                      discord.Color.red())
        try:
            file = discord.File(fp=generate_game_results_image(game, tn),
                                filename=f"game_{game['match_id']}.png")
        except Exception as e:
            print(f"[{COG_NAME}] Image error: {e}")
            file = None

        embed = discord.Embed(
            title=f"🏒 Match {game['match_id']}",
            description=(f"**{t1}** `{game['score_t1']}` — `{game['score_t2']}` **{t2}**\n"
                         f"**{game['result_t1']}** / **{game['result_t2']}** "
                         f"| 🕐 {game['game_minutes']} min | {type_label} | {game['date']}"),
            color=colour
        )
        embed.set_footer(text=f"{_get_league_name()} • Game Results v{VERSION} • Select a player below")
        view = PlayerView(game["all_players"], game["match_id"], tn)
        if file:
            await interaction.followup.send(file=file, ephemeral=True)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class GameSelectView(discord.ui.View):
    def __init__(self, summary, team_names):
        super().__init__(timeout=180)
        self.add_item(GameSelect(summary, team_names))


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class GameResults(commands.Cog):
    def __init__(self, bot):
        self.bot             = bot
        self._last_match_ids = set()
        self.season_update_loop.start()
        print(f"🏒 [{COG_NAME}] Cog initialized — v{VERSION}")

    def cog_unload(self):
        self.season_update_loop.cancel()

    async def _refresh_season_image(self, summary: list, team_names: dict,
                                     force: bool = False):
        cid = self.bot.config.get("results_channel_id")
        if not cid:
            print(f"[{COG_NAME}] results_channel_id not set — skipping season image.")
            return
        channel = self.bot.get_channel(int(cid))
        if not channel:
            print(f"[{COG_NAME}] Could not find channel {cid}")
            return
        try:
            fn     = getattr(utils, "generate_season_summary_image", generate_season_summary_image)
            result = fn(summary, team_names)
            if isinstance(result, list):
                if result and isinstance(result[0], tuple) and len(result[0]) == 3:
                    pages = result
                elif result and isinstance(result[0], tuple):
                    pages = [(b, l, False) for b, l in result]
                else:
                    pages = [(b, "", False) for b in result]
            else:
                pages = [(result, "", True)]
        except Exception as e:
            print(f"[{COG_NAME}] Season image error: {e}")
            return

        past_pages    = [(buf, lbl) for buf, lbl, cur in pages if not cur]
        current_pages = [(buf, lbl) for buf, lbl, cur in pages if cur]

        past_ids   = self.bot.config.get("season_results_past_ids", [])
        current_id = self.bot.config.get("season_results_current_id")

        for legacy_key in ("season_results_message_ids", "season_results_message_id"):
            legacy_val = self.bot.config.get(legacy_key)
            if legacy_val is None:
                continue
            old_ids = legacy_val if isinstance(legacy_val, list) else [legacy_val]
            for old_id in old_ids:
                try:
                    m = await channel.fetch_message(int(old_id))
                    await m.delete()
                except Exception:
                    pass
            self.bot.config.pop(legacy_key, None)

        new_past_count = len(past_pages)

        if force or len(past_ids) != new_past_count:
            for old_id in past_ids:
                try:
                    m = await channel.fetch_message(int(old_id))
                    await m.delete()
                except Exception:
                    pass
            if current_id:
                try:
                    m = await channel.fetch_message(int(current_id))
                    await m.delete()
                except Exception:
                    pass
                current_id = None

            new_past_ids = []
            for i, (buf, lbl) in enumerate(past_pages):
                try:
                    msg = await channel.send(
                        file=discord.File(fp=buf, filename=f"results_week_{i+1}.png")
                    )
                    new_past_ids.append(str(msg.id))
                    print(f"[{COG_NAME}] Past week {i+1} posted (msg {msg.id})")
                except Exception as e:
                    print(f"[{COG_NAME}] Failed to post past week {i+1}: {e}")
            past_ids = new_past_ids

        if current_id:
            try:
                m = await channel.fetch_message(int(current_id))
                await m.delete()
            except Exception:
                pass

        new_current_id = None
        if current_pages:
            buf, lbl = current_pages[-1]
            try:
                msg = await channel.send(
                    file=discord.File(fp=buf, filename="results_current_week.png")
                )
                new_current_id = str(msg.id)
                print(f"[{COG_NAME}] Current week posted (msg {msg.id})")
            except Exception as e:
                print(f"[{COG_NAME}] Failed to post current week: {e}")

        self.bot.config["season_results_past_ids"]   = past_ids
        self.bot.config["season_results_current_id"] = new_current_id
        utils.save_config(self.bot.config)

    @tasks.loop(minutes=5)
    async def season_update_loop(self):
        try:
            loop = asyncio.get_event_loop()
            sh = await loop.run_in_executor(None, utils.get_sheet)
            if not sh: return
            summary, team_names = _build_game_rows(sh, self.bot.config)
            if not summary: return
            current_ids = {g["match_id"] for g in summary}
            if current_ids != self._last_match_ids:
                new = current_ids - self._last_match_ids
                if new:
                    print(f"[{COG_NAME}] {len(new)} new match(es) — refreshing season image.")
                self._last_match_ids = current_ids
                await self._refresh_season_image(summary, team_names)
        except Exception as e:
            print(f"[{COG_NAME}] season_update_loop error: {e}")

    @season_update_loop.before_loop
    async def before_season_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="updateresults",
                          description="[Admin] Rebuild Game Results sheet + refresh season image.")
    @app_commands.checks.has_permissions(administrator=True)
    async def updateresults(self, interaction: discord.Interaction):
        await interaction.response.defer()
        loop = asyncio.get_event_loop()
        sh = await loop.run_in_executor(None, utils.get_sheet)
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.")
        summary, team_names = _build_game_rows(sh, self.bot.config)
        if not summary:
            return await interaction.followup.send("⚠️ No game data found in Player Stats tab.")
        count, tab = _write_results_tab(sh, summary, team_names)
        await self._refresh_season_image(summary, team_names)
        await interaction.followup.send(
            f"✅ **Game Results** updated!\n"
            f"📋 `{count}` games written to **{tab}** sheet.\n"
            f"🖼️ Season summary image refreshed in results channel."
        )

    @app_commands.command(name="refreshresults",
                          description="[Admin] Force-repost ALL result pages (use after a merge/unmerge).")
    @app_commands.checks.has_permissions(administrator=True)
    async def refreshresults(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loop = asyncio.get_event_loop()
        sh = await loop.run_in_executor(None, utils.get_sheet)
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)
        summary, team_names = _build_game_rows(sh, self.bot.config)
        if not summary:
            return await interaction.followup.send("⚠️ No game data found.", ephemeral=True)
        await interaction.followup.send("🔄 Force-reposting all result pages...", ephemeral=True)
        await self._refresh_season_image(summary, team_names, force=True)
        await interaction.edit_original_response(
            content=f"✅ All result pages reposted — {len(summary)} games."
        )

    @app_commands.command(name="gameresults",
                          description="Browse game results — scoreboard image + per-player stats.")
    async def gameresults(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loop = asyncio.get_event_loop()
        sh = await loop.run_in_executor(None, utils.get_sheet)
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)
        summary, team_names = _build_game_rows(sh, self.bot.config)
        if not summary:
            return await interaction.followup.send(
                "⚠️ No game data found. Make sure Player Stats has data.", ephemeral=True)
        reg = sum(1 for g in summary if g["game_type"] == "REG")
        ot  = sum(1 for g in summary if g["game_type"] == "OT")
        dnf = sum(1 for g in summary if g["game_type"] == "DNF")
        embed = discord.Embed(
            title=f"🏒 {_get_league_name()} — Game Results",
            description=(f"**{len(summary)}** games this season.\n"
                         f"🟩 Regulation: `{reg}` | 🟨 OT: `{ot}` | 🟧 DNF: `{dnf}`\n\n"
                         "Select a game below for the scoreboard image and player stats."),
            color=discord.Color.from_str("#C9A84C")
        )
        embed.set_footer(text=f"{_get_league_name()} • Game Results v{VERSION}")
        await interaction.followup.send(embed=embed, view=GameSelectView(summary, team_names), ephemeral=True)

    @app_commands.command(name="listteamids",
                          description="[Admin] Show all team IDs seen this season and their resolved names.")
    @app_commands.checks.has_permissions(administrator=True)
    async def listteamids(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loop = asyncio.get_event_loop()
        sh = await loop.run_in_executor(None, utils.get_sheet)
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)
        summary, team_names = _build_game_rows(sh, self.bot.config)
        if not team_names:
            return await interaction.followup.send("⚠️ No team data found.", ephemeral=True)

        overrides = {str(k): str(v) for k, v in self.bot.config.get("team_ids", {}).items()}
        lines = []
        for tid, name in sorted(team_names.items()):
            src = "📌 config override" if tid in overrides else "🔍 auto-resolved"
            lines.append(f"`{tid}` → **{name}** ({src})")

        embed = discord.Embed(
            title="🏒 Team ID Map — This Season",
            description="\n".join(lines) or "No teams found.",
            color=discord.Color.from_str("#C9A84C")
        )
        embed.set_footer(text=f"Use /fixteamnames to pin a team_id → name override  •  v{VERSION}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="fixteamnames",
                          description="[Admin] Manually pin a team ID to a display name.")
    @app_commands.describe(
        team_id="The raw numeric team ID (use /listteamids to find it)",
        name="The display name you want this team to show as"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fixteamnames(self, interaction: discord.Interaction, team_id: str, name: str):
        await interaction.response.defer(ephemeral=True)
        team_id = team_id.strip()
        name    = name.strip()
        if not team_id or not name:
            return await interaction.followup.send("❌ Both team_id and name are required.", ephemeral=True)
        if "team_ids" not in self.bot.config:
            self.bot.config["team_ids"] = {}
        old_name = self.bot.config["team_ids"].get(team_id, "not set")
        self.bot.config["team_ids"][team_id] = name
        utils.save_config(self.bot.config)
        await interaction.followup.send(
            f"✅ Team name pinned!\n`{team_id}` → **{name}**\n*(was: {old_name})*\n\n"
            f"Run `/updateresults` to rebuild the season image with the new name.",
            ephemeral=True
        )

    @fixteamnames.error
    async def fixteamnames_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(GameResults(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
