__version__ = "5.9-SHEET-RETRY"
print(f"--- Utils Version: {__version__} ---")

import os
import json
import gspread
import asyncio
import aiohttp
import io
import textwrap
from datetime import datetime
import time as t_time
from PIL import Image, ImageDraw, ImageFont
import discord

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
SHEET_ID = "1YUC4x0_Py4f9KbTPhXniddd8GvrKL1KRx6iLo5DdBq0"

# --- 🔒 LOCKED SCRAPER HEADERS ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Referer': 'https://www.ea.com/',
    'Origin': 'https://www.ea.com',
    'Accept': 'application/json, text/plain, */*',
    'Connection': 'keep-alive'
}

def load_config():
    default = {"team_ids": {}, "processed_match_ids": [], "announcement_channel_id": 0, "logging_channel_id": 0, "platform": "common-gen5", "google_sheet_name": "MyStatsSheet"}
    if not os.path.exists(CONFIG_FILE): save_config(default); return default
    try:
        with open(CONFIG_FILE, 'r') as f: return {**default, **json.load(f)}
    except: return default

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)

async def send_log(bot, message):
    print(f"[LOG] {message}")
    cid = bot.config.get("logging_channel_id")
    if cid:
        try:
            channel = bot.get_channel(int(cid))
            if channel: await channel.send(f"`[{datetime.now().strftime('%H:%M:%S')}] {message}`")
        except: pass

def get_sheet(retries=3, backoff=15):
    """
    Connect to Google Sheets with retry logic.
    On 429 rate-limit: retries up to `retries` times, sleeping `backoff` seconds
    between each attempt (backoff doubles each retry: 15s, 30s, 60s).
    Returns None only after all retries are exhausted or a non-429 error occurs.
    """
    for attempt in range(1, retries + 1):
        try:
            gc = gspread.service_account(filename=os.path.join(BASE_DIR, 'credentials.json'))
            return gc.open_by_key(SHEET_ID)
        except Exception as e:
            if "429" in str(e):
                wait = backoff * (2 ** (attempt - 1))  # 15s, 30s, 60s
                print(f"[Utils] get_sheet() 429 rate limit — attempt {attempt}/{retries}, retrying in {wait}s...")
                t_time.sleep(wait)
            else:
                print(f"[Utils] get_sheet() error: {e}")
                return None
    print(f"[Utils] get_sheet() failed after {retries} retries.")
    return None

def find_header_row(rows, required_cols=["Match ID", "Username"]):
    for i, row in enumerate(rows[:10]):
        clean = [str(x).strip() for x in row]
        if all(c in clean for c in required_cols): return i, clean
    return -1, []

def get_all_match_ids():
    sh = get_sheet()
    if not sh: return []
    try: return sh.worksheet("Player Stats").col_values(1)[1:] 
    except: return []

# --- GRAPHICS ENGINE ---
def get_base_image_context(width=1600, height=1400):
    img = Image.new('RGB', (width, height), color='#0d1117')
    try:
        bg = Image.open(os.path.join(BASE_DIR, "background.png")).resize((width, height)).convert('RGBA')
        overlay = Image.new('RGBA', bg.size, (13, 17, 23, 215)) 
        img = Image.alpha_composite(bg, overlay).convert('RGB')
    except: pass
    
    draw = ImageDraw.Draw(img)
    def get_font(size):
        try: return ImageFont.truetype(os.path.join(BASE_DIR, "font.ttf"), size)
        except: return ImageFont.load_default()
        
    f = {
        "title": get_font(70), "header": get_font(40), "row": get_font(30), 
        "h1": get_font(80), "h2": get_font(50), "val": get_font(40), 
        "lbl": get_font(24), "small": get_font(22), 
        "score": get_font(90), "team": get_font(50)  # Shrunk slightly to un-cramp header
    }
    return img, draw, f

def _draw_stat_block(draw, fonts, x, y, label, value):
    draw.text((x - draw.textlength(label, font=fonts["lbl"])/2, y), label, font=fonts["lbl"], fill="#aaaaaa")
    draw.text((x - draw.textlength(str(value), font=fonts["val"])/2, y + 30), str(value), font=fonts["val"], fill="#ffffff")

# --- IMAGE GENERATORS ---

def generate_player_card(name, stats, logs, team_name):
    # 'stats' is now a nested dictionary containing Total, Forward, Defense, and Goalie splits
    img, draw, fonts = get_base_image_context(1200, 950)
    draw.rectangle((0, 0, 1200, 160), fill="#010409")
    draw.text((50, 40), name, font=fonts["h1"], fill="white")
    draw.text((50, 120), team_name, font=fonts["row"], fill="#58a6ff")
    
    draw.text((50, 200), "CAREER TOTALS", font=fonts["h2"], fill="white")
    draw.line((50, 260, 1150, 260), fill="#30363d", width=2)
    
    tot = stats.get('Total', {})
    is_goalie = tot.get('Main Position') == 'Goalie'
    
    if is_goalie:
        sv, ga, gp = tot.get('Sv', 0), tot.get('GA', 0), tot.get('GP', 0)
        sa = sv + ga
        svp = f"{(sv/sa):.3f}" if sa > 0 else "0.000"
        gaa = f"{(ga/gp):.2f}" if gp > 0 else "0.00"
        s_list = [("GP", gp), ("SA", sa), ("SV", sv), ("GA", ga), ("SV%", svp), ("GAA", gaa), ("AST", tot.get('A',0)), ("PTS", tot.get('P',0))]
    else:
        s_list = [("GP", tot.get('GP',0)), ("GOALS", tot.get('G',0)), ("ASSISTS", tot.get('A',0)), ("POINTS", tot.get('P',0)), ("+/-", tot.get('+/-',0)), ("HITS", tot.get('Hits',0)), ("SHOTS", tot.get('S',0)), ("PIM", tot.get('PIM',0))]
    
    sx = 80
    for lbl, val in s_list:
        _draw_stat_block(draw, fonts, sx, 290, lbl, val)
        sx += 140
        
    draw.text((50, 450), "POSITIONAL SPLITS", font=fonts["h2"], fill="white")
    draw.line((50, 510, 1150, 510), fill="#30363d", width=2)
    
    y_pos = 540
    for pos in ['Forward', 'Defense', 'Goalie']:
        p_data = stats.get(pos, {})
        if p_data.get('GP', 0) > 0:
            draw.text((50, y_pos), f"{pos.upper()}", font=fonts["header"], fill="#58a6ff")
            
            if pos == 'Goalie':
                sv, ga, gp = p_data.get('Sv', 0), p_data.get('GA', 0), p_data.get('GP', 0)
                sa = sv + ga
                svp = f"{(sv/sa):.3f}" if sa > 0 else "0.000"
                gaa = f"{(ga/gp):.2f}" if gp > 0 else "0.00"
                stat_str = f"GP: {gp}   |   SA: {sa}   |   SV: {sv}   |   GA: {ga}   |   SV%: {svp}   |   GAA: {gaa}   |   AST: {p_data.get('A',0)}   |   PTS: {p_data.get('P',0)}"
            else:
                stat_str = f"GP: {p_data.get('GP',0)}   |   G: {p_data.get('G',0)}   |   A: {p_data.get('A',0)}   |   PTS: {p_data.get('P',0)}   |   +/-: {p_data.get('+/-',0)}   |   S: {p_data.get('S',0)}   |   H: {p_data.get('Hits',0)}   |   PIM: {p_data.get('PIM',0)}"
            
            draw.text((50, y_pos + 50), stat_str, font=fonts["row"], fill="white")
            y_pos += 120
            
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

def generate_roster_image(roster_data, config):
    img, draw, fonts = get_base_image_context(1400, 6000)
    draw.text((50, 40), "TEAM ROSTERS", font=fonts["title"], fill="white")
    draw.line((50, 120, 1350, 120), fill="#30363d", width=3)
    y = 160
    for tid, players in roster_data.items():
        tname = config["team_ids"].get(tid, f"Team {tid}")
        draw.text((50, y), tname.upper(), font=fonts["h2"], fill="#58a6ff")
        y += 60
        sorted_players = sorted(players.items(), key=lambda x: x[1], reverse=True)
        col_x = [80, 520, 960]
        current_col = 0
        start_y = y
        max_y = y
        for name, gp in sorted_players:
            draw.text((col_x[current_col], y), f"{name[:15]}", font=fonts["row"], fill="white")
            draw.text((col_x[current_col] + 250, y), f"{gp} GP", font=fonts["row"], fill="#aaaaaa")
            y += 45
            if y > max_y: max_y = y
            if (y - start_y) > 450: 
                current_col += 1; y = start_y
                if current_col > 2: break 
        y = max_y + 60
        draw.line((50, y-20, 1350, y-20), fill="#30363d", width=2)
    img = img.crop((0, 0, 1400, y+50))
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

def generate_game_report(game_data):
    width, height = 1500, 3600 
    img, draw, fonts = get_base_image_context(width, height)
    colors = {"home": "#58a6ff", "away": "#f85149", "dark": "#010409", "gold": "#FFD700", "silver": "#C0C0C0", "bronze": "#CD7F32"}

    try:
        c_ids = list(game_data['clubs'].keys())
        c1_id, c2_id = c_ids[0], c_ids[1]
        c1, c2 = game_data['clubs'][c1_id], game_data['clubs'][c2_id]
        
        # SCOREBOARD (Un-cramped Header)
        draw.rectangle((0, 0, width, 220), fill=colors["dark"])
        c1_name = c1['details']['name'][:18].upper()
        c2_name = c2['details']['name'][:18].upper()
        
        draw.text((50, 70), c1_name, font=fonts["team"], fill="white")
        w2 = draw.textlength(c2_name, font=fonts["team"])
        draw.text((width - 50 - w2, 70), c2_name, font=fonts["team"], fill="white")
        
        stxt = f"{c1['score']}   -   {c2['score']}"
        sw = draw.textlength(stxt, font=fonts["score"])
        draw.text(((width-sw)/2, 60), stxt, font=fonts["score"], fill="white")
        
        # TEAM STATS
        def get_totals(cid):
            pl = game_data['players'].get(cid, {})
            t = {'S':0, 'H':0, 'TOA':0, 'FOW':0, 'FOL':0, 'PIM':0}
            for p in pl.values():
                def g(k): return int(float(p.get(k, 0)))
                t['S']+=g('skshots'); t['H']+=g('skhits'); t['TOA']+=g('skpossession')
                t['FOW']+=g('skfow'); t['FOL']+=g('skfol'); t['PIM']+=g('skpim')
            return t
            
        t1, t2 = get_totals(c1_id), get_totals(c2_id)
        ty = 270
        draw.text((width//2 - draw.textlength("TEAM STATS", fonts["h2"])//2, ty), "TEAM STATS", font=fonts["h2"], fill="white")
        ty += 80
        
        def draw_comp(y, lbl, v1, v2):
            draw.text((width//2 - draw.textlength(lbl, fonts["header"])//2, y), lbl, font=fonts["header"], fill="#aaaaaa")
            draw.text((300, y), str(v1), font=fonts["header"], fill=colors["home"])
            draw.text((width - 300 - draw.textlength(str(v2), fonts["header"]), y), str(v2), font=fonts["header"], fill=colors["away"])
            
        t1_toa = f"{t1['TOA']//60}:{t1['TOA']%60:02d}"
        t2_toa = f"{t2['TOA']//60}:{t2['TOA']%60:02d}"
        
        draw_comp(ty, "SHOTS", t1['S'], t2['S']); ty += 55
        draw_comp(ty, "HITS", t1['H'], t2['H']); ty += 55
        draw_comp(ty, "TIME ON ATTACK", t1_toa, t2_toa); ty += 55
        draw_comp(ty, "FACEOFF WINS", t1['FOW'], t2['FOW']); ty += 55
        draw_comp(ty, "PENALTY MINS", t1['PIM'], t2['PIM']); ty += 100

        # CONDENSED 3 STARS
        sy = ty
        draw.text((width//2 - draw.textlength("THREE STARS OF THE GAME", fonts["h2"])//2, sy), "THREE STARS OF THE GAME", font=fonts["h2"], fill="white")
        
        all_p = []
        for cid, pl in game_data['players'].items():
            for p in pl.values(): all_p.append(p)
            
        all_p.sort(key=lambda p: (float(p.get('glsaves',0))*0.5 - float(p.get('glga',0)) + 10) if p.get('position')=='goalie' else (float(p.get('skgoals',0))*3 + float(p.get('skassists',0))*2), reverse=True)
        
        ranks = ["1ST STAR", "2ND STAR", "3RD STAR"]
        sc = [colors["gold"], colors["silver"], colors["bronze"]]
        sty = sy + 70
        
        for i, p in enumerate(all_p[:3]):
            pn = p.get('playername')[:20]
            st = f"{int(float(p.get('glsaves',0)))} SV" if p.get('position')=='goalie' else f"{int(float(p.get('skgoals',0)))}G {int(float(p.get('skassists',0)))}A"
            star_txt = f"{ranks[i]}: {pn} ({st})"
            draw.text((width//2 - draw.textlength(star_txt, fonts["header"])/2, sty), star_txt, font=fonts["header"], fill=sc[i])
            sty += 55

        # SKATER / GOALIE TABLES
        y_offset = sty + 80
        for cid in [c1_id, c2_id]:
            c_name = game_data['clubs'][cid]['details']['name']
            draw.rectangle((0, y_offset, width, y_offset+80), fill=colors["dark"])
            draw.text((50, y_offset+15), f"{c_name.upper()} - SKATERS", font=fonts["h2"], fill="white")
            y_offset += 100
            
            headers = ["Player", "Pos", "G", "A", "PTS", "+/-", "S", "H", "PIM"]
            hx = [50, 310, 530, 630, 730, 850, 970, 1090, 1210]
            for i, h in enumerate(headers): draw.text((hx[i], y_offset), h, font=fonts["header"], fill="#58a6ff")
            y_offset += 60
            
            players = list(game_data['players'][cid].values())
            skaters = [p for p in players if p.get('position') != 'goalie']
            goalies = [p for p in players if p.get('position') == 'goalie']
            
            for p in skaters:
                def g(k): return int(float(p.get(k, 0)))
                row = [p.get('playername')[:18], p.get('position').capitalize(), str(g('skgoals')), str(g('skassists')), str(g('skgoals')+g('skassists')), str(g('skplusmin')), str(g('skshots')), str(g('skhits')), str(g('skpim'))]
                for i, v in enumerate(row): 
                    fill_c = "white" if i == 0 else "#aaaaaa"
                    draw.text((hx[i], y_offset), v, font=fonts["row"], fill=fill_c)
                y_offset += 50
            
            y_offset += 60
            draw.rectangle((0, y_offset, width, y_offset+80), fill=colors["dark"])
            draw.text((50, y_offset+15), f"{c_name.upper()} - GOALIES", font=fonts["h2"], fill="white")
            y_offset += 100
            
            gh = ["Player", "SA", "SV", "GA", "SV%"]
            gx = [50, 500, 700, 900, 1100]
            for i, h in enumerate(gh): draw.text((gx[i], y_offset), h, font=fonts["header"], fill="#58a6ff")
            y_offset += 60
            
            for p in goalies:
                sv, ga = int(float(p.get('glsaves',0))), int(float(p.get('glga',0)))
                sa = sv + ga
                svp = f"{(sv/sa):.3f}" if sa > 0 else "0.000"
                row = [p.get('playername')[:18], str(sa), str(sv), str(ga), svp]
                for i, v in enumerate(row): 
                    fill_c = "white" if i == 0 else "#aaaaaa"
                    draw.text((gx[i], y_offset), v, font=fonts["row"], fill=fill_c)
                y_offset += 50
            y_offset += 100

        img = img.crop((0, 0, width, y_offset))
    except Exception as e: print(f"Error drawing details: {e}")

    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

def generate_wide_team_card(team_name, roster_stats):
    img, draw, fonts = get_base_image_context(1800, 1400)
    colors = {"pos": "#3fb950", "neg": "#f85149", "cold": "#58a6ff", "text": "white", "grey": "#aaaaaa"}
    draw.text((50, 40), f"{team_name.upper()} - TEAM STATS", font=fonts["h1"], fill="white")
    draw.line((50, 120, 1750, 120), fill="#58a6ff", width=6)
    headers = ["Player", "GP", "G", "A", "P", "+/-", "Hits", "S", "PIM", "Sv", "GA", "Sv%"]
    xs = [50, 400, 500, 600, 700, 800, 900, 1000, 1100, 1250, 1350, 1450]
    hy = 160
    for i, h in enumerate(headers): draw.text((xs[i], hy), h, font=fonts["h2"], fill="#58a6ff")
    ry = 230
    sorted_roster = sorted(roster_stats, key=lambda x: x[1].get('P', 0), reverse=True)
    for name, s in sorted_roster:
        is_g = s.get('Main Position') == 'Goalie'
        row_col = colors["cold"] if is_g else colors["text"]
        pm_val = s.get('+/-', 0); pm_c = colors["pos"] if pm_val > 0 else (colors["neg"] if pm_val < 0 else colors["grey"])
        if is_g: sv, ga, svp = str(s.get('Sv',0)), str(s.get('GA',0)), f"{s.get('Save % Value',0):.3f}"
        else: sv, ga, svp = "-", "-", "-"
        draw.text((xs[0], ry), name[:18], font=fonts["row"], fill=row_col)
        draw.text((xs[1], ry), str(s.get('GP',0)), font=fonts["row"], fill=colors["grey"])
        draw.text((xs[2], ry), str(s.get('G',0)), font=fonts["row"], fill=colors["text"])
        draw.text((xs[3], ry), str(s.get('A',0)), font=fonts["row"], fill=colors["text"])
        draw.text((xs[4], ry), str(s.get('P',0)), font=fonts["val"], fill="#58a6ff")
        draw.text((xs[5], ry), str(pm_val), font=fonts["row"], fill=pm_c)
        draw.text((xs[6], ry), str(s.get('Hits',0)), font=fonts["row"], fill=colors["grey"])
        draw.text((xs[7], ry), str(s.get('S',0)), font=fonts["row"], fill=colors["grey"])
        draw.text((xs[8], ry), str(s.get('PIM',0)), font=fonts["row"], fill=colors["grey"])
        draw.text((xs[9], ry), sv, font=fonts["row"], fill=colors["grey"])
        draw.text((xs[10], ry), ga, font=fonts["row"], fill=colors["grey"])
        draw.text((xs[11], ry), svp, font=fonts["row"], fill=colors["grey"])
        ry += 50
        if ry > 1350: break
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

def generate_leaderboard_image(season_stats):
    img, draw, fonts = get_base_image_context(1600, 1400)
    draw.text((50, 40), "LEAGUE LEADERS", font=fonts["title"], fill="white")
    draw.line((50, 120, 1550, 120), fill="#30363d", width=3)
    categories = [
        {"key": "P", "name": "POINTS", "pos": "Skater"}, {"key": "G", "name": "GOALS", "pos": "Skater"}, 
        {"key": "A", "name": "ASSISTS", "pos": "Skater"}, {"key": "Hits", "name": "HITS", "pos": "Skater"}, 
        {"key": "Save % Value", "name": "SAVE %", "pos": "Goalie"}, {"key": "Sv", "name": "SAVES", "pos": "Goalie"}
    ]
    sx, sy = 50, 160; cw, rh = 500, 400
    for index, cat in enumerate(categories):
        col, row = index % 3, index // 3
        x, y = sx + (col * cw), sy + (row * rh)
        draw.text((x, y), cat["name"], font=fonts["header"], fill="#58a6ff")
        players = []
        for n, s in season_stats.items():
            if s['Main Position'] == cat['pos']:
                if "SAVE" in cat["name"].upper() and s['GP'] < 3: continue
                players.append((n, s))
        players.sort(key=lambda x: x[1].get(cat['key'], 0), reverse=True)
        ly = y + 60
        for i, (name, stats) in enumerate(players[:10], 1):
            val = stats.get(cat['key'], 0)
            v_str = f"{val:.3f}" if "SAVE" in cat["name"].upper() else str(int(val))
            draw.text((x, ly), f"{i}. {name[:13]}", font=fonts["row"], fill="white")
            draw.text((x+300, ly), v_str, font=fonts["row"], fill="#aaaaaa")
            ly += 35
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

def generate_standings_image(standings_data):
    h = 250 + (len(standings_data) * 65)
    img, draw, fonts = get_base_image_context(1600, h)
    draw.text((50, 40), "LEAGUE STANDINGS", font=fonts["title"], fill="white")
    headers = ["Rank", "Team Name", "GP", "W", "L", "OTL", "PTS", "GF", "GA", "Diff"]
    xs = [50, 150, 650, 750, 850, 950, 1050, 1150, 1280, 1420]
    for i, txt in enumerate(headers): draw.text((xs[i], 150), txt, font=fonts["header"], fill="#58a6ff")
    draw.line((50, 200, 1550, 200), fill="#30363d", width=3)
    ry = 220
    for row in standings_data:
        for i, val in enumerate(row): draw.text((xs[i], ry), str(val), font=fonts["row"], fill="white")
        ry += 65
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    return buf

# --- 🔒 LOCKED API FETCHERS ---
async def warm_up_session(session):
    try:
        async with session.get("https://www.ea.com", headers=HEADERS, timeout=10) as r: return r.status == 200
    except: return False

async def get_recent_games(session, club_id, platform, match_type):
    url = "https://proclubs.ea.com/api/nhl/clubs/matches"
    params = {'matchType': match_type, 'platform': platform, 'clubIds': club_id}
    try:
        async with session.get(url, params=params, headers=HEADERS, timeout=15) as r: return await r.json() if r.status == 200 else None
    except: return None

async def find_club(session, name, platform):
    url = "https://proclubs.ea.com/api/nhl/clubs/search"
    try:
        async with session.get(url, params={'platform': platform, 'clubName': name}, headers=HEADERS) as r:
            data = await r.json()
            if not data: return None
            return str(list(data.values())[0]['clubId'])
    except: return None

# --- DATABASE LOGGING AND READING ---
def log_game_data(game, config, cached_ids=None):
    sh = get_sheet()
    if not sh: return "Error"
    try:
        ws = sh.worksheet("Player Stats")
        mid = str(game['matchId'])
        if cached_ids and mid in cached_ids: return "Duplicate"
        
        rows = []
        for cid, players in game['players'].items():
            for pid, p in players.items():
                def g(k): return int(float(p.get(k, 0)))
                row = [
                    mid, datetime.now().strftime('%Y-%m-%d'), pid, p.get('playername'), config['platform'], cid, p.get('position'), 
                    g('skgoals'), g('skassists'), g('skgoals')+g('skassists'), g('skshots'), 
                    0,0,0, g('skhits'), g('skblockedshots'), g('sktakeaways'), g('skdeflections'), g('skfol'), g('skfow'), 
                    0, g('skgiveaways'), g('skgwg'), g('skinterceptions'), g('skpassattempts'), g('skpasses'), 
                    0, g('skpenaltiesdrawn'), g('skpim'), g('skpkzoneclears'), g('skplusmin'), g('skpossession'), 
                    g('skppg'), g('sksaucerpasses'), g('skshg'), g('skshotattempts'), 
                    0, 0, p.get('toiseconds'), g('glsaves'), g('glga'), 0
                ]
                rows.append(row)
        ws.append_rows(rows, value_input_option='USER_ENTERED')
 # ---> OUR NEW SHADOW FUNNEL <---
        try:
            log_all_stats_shadow(game, config, sh)
        except:
            pass
        return f"Logged {mid}"
    except Exception as e: return f"Error: {e}"

def format_game_embed(game, config):
    t1, t2 = list(game['clubs'].values())[0], list(game['clubs'].values())[1]
    e = discord.Embed(title=f"Match {game['matchId']}", description=f"**{t1['details']['name']} {t1['score']} - {t2['score']} {t2['details']['name']}**", color=discord.Color.dark_gray())
    return e

def get_roster_data_from_sheet(config):
    rosters = {str(tid): {} for tid in config.get("team_ids", {})}
    sh = get_sheet()
    if not sh: return rosters
    try:
        ws = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = find_header_row(rows, ["Team ID", "Username"])
        if h_idx != -1:
             i_cid = h.index("Team ID"); i_name = h.index("Username")
             for r in rows[h_idx+1:]:
                 if len(r) > i_cid:
                     cid = str(r[i_cid]).strip(); name = str(r[i_name]).strip()
                     if cid in rosters and name:
                         rosters[cid][name] = rosters[cid].get(name, 0) + 1
    except: pass
    return rosters

def get_season_stats_from_sheet(config):
    stats = {}
    sh = get_sheet()
    if not sh: return {}
    try:
        ws = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = find_header_row(rows, ["Username", "Team ID"])
        if h_idx == -1: return {}
        def idx(c): return h.index(c)
        col_pm = "+/-" if "+/-" in h else ("Plus/Minus" if "Plus/Minus" in h else None)
        
        for r in rows[h_idx+1:]:
            if len(r) <= idx("Username"): continue
            n = r[idx("Username")]
            if not n: continue
            if n not in stats:
                pos = r[idx("Position")] if "Position" in h else "Skater"
                stats[n] = {
                    'GP':0,'G':0,'A':0,'P':0,'Hits':0,'Sv':0,'GA':0,'S':0,'PIM':0,'+/-':0, 
                    'Main Position': 'Goalie' if 'goalie' in str(pos).lower() else 'Skater'
                }
            s = stats[n]; s['GP'] += 1
            def v(c): 
                try: return int(float(str(r[idx(c)]).replace('%','')))
                except: return 0
                
            if "Goals" in h: s['G']+=v("Goals")
            if "Assists" in h: s['A']+=v("Assists")
            if "Points" in h: s['P']+=v("Points")
            if "Hits" in h: s['Hits']+=v("Hits")
            if "Saves" in h: s['Sv']+=v("Saves")
            if "Goals Against" in h: s['GA']+=v("Goals Against")
            if "Shots" in h: s['S']+=v("Shots")
            if "PIMs" in h: s['PIM']+=v("PIMs")
            if col_pm: s['+/-']+=v(col_pm)
            
            if s['Main Position']=='Goalie': 
                t = s['Sv']+s['GA']
                s['Save % Value'] = s['Sv']/t if t>0 else 0.0
        return stats
    except: return {}

def get_detailed_stats(target, is_team=False): 
    sh = get_sheet()
    target = target.strip().lower()
    
    data = {
        'Total': {'GP':0,'G':0,'A':0,'P':0,'Hits':0,'Sv':0,'GA':0,'S':0,'PIM':0,'+/-':0, 'Main Position': 'Skater'},
        'Forward': {'GP':0,'G':0,'A':0,'P':0,'Hits':0,'S':0,'PIM':0,'+/-':0},
        'Defense': {'GP':0,'G':0,'A':0,'P':0,'Hits':0,'S':0,'PIM':0,'+/-':0},
        'Goalie': {'GP':0,'Sv':0,'GA':0,'A':0,'P':0, 'PIM':0}
    }
    
    if not sh: return data
    try:
        ws = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = find_header_row(rows, ["Username"])
        if h_idx == -1: return data
        def idx(c): return h.index(c) if c in h else -1
        col_pm = idx("+/-") if "+/-" in h else (idx("Plus/Minus") if "Plus/Minus" in h else -1)
        
        skater_games = 0
        goalie_games = 0
        
        for r in rows[h_idx+1:]:
            if len(r) <= idx("Username") or idx("Username") == -1: continue
            n = str(r[idx("Username")]).strip().lower()
            if n != target: continue
            
            pos_raw = str(r[idx("Position")]).lower() if idx("Position") != -1 else "forward"
            if 'goalie' in pos_raw or pos_raw == 'g':
                pos_cat = 'Goalie'
                goalie_games += 1
            elif 'defense' in pos_raw or pos_raw in ['ld', 'rd', 'd']:
                pos_cat = 'Defense'
                skater_games += 1
            else:
                pos_cat = 'Forward'
                skater_games += 1
                
            def v(c):
                i = idx(c)
                if i != -1 and i < len(r):
                    try: return int(float(str(r[i]).replace('%','')))
                    except: return 0
                return 0
                
            # Add to Total
            data['Total']['GP'] += 1
            data['Total']['G'] += v("Goals")
            data['Total']['A'] += v("Assists")
            data['Total']['P'] += v("Points")
            data['Total']['Hits'] += v("Hits")
            data['Total']['Sv'] += v("Saves")
            data['Total']['GA'] += v("Goals Against")
            data['Total']['S'] += v("Shots")
            data['Total']['PIM'] += v("PIMs")
            if col_pm != -1 and col_pm < len(r):
                try: data['Total']['+/-'] += int(float(str(r[col_pm])))
                except: pass
                
            # Add to Specific Position
            data[pos_cat]['GP'] += 1
            if pos_cat == 'Goalie':
                data[pos_cat]['Sv'] += v("Saves")
                data[pos_cat]['GA'] += v("Goals Against")
                data[pos_cat]['A'] += v("Assists")
                data[pos_cat]['P'] += v("Points")
                data[pos_cat]['PIM'] += v("PIMs")
            else:
                data[pos_cat]['G'] += v("Goals")
                data[pos_cat]['A'] += v("Assists")
                data[pos_cat]['P'] += v("Points")
                data[pos_cat]['Hits'] += v("Hits")
                data[pos_cat]['S'] += v("Shots")
                data[pos_cat]['PIM'] += v("PIMs")
                if col_pm != -1 and col_pm < len(r):
                    try: data[pos_cat]['+/-'] += int(float(str(r[col_pm])))
                    except: pass
                    
        data['Total']['Main Position'] = 'Goalie' if goalie_games > skater_games else 'Skater'
        return data
    except Exception as e:
        print(f"Stats Error: {e}")
        return data

def get_player_game_log(player_name, config):
    return [] # Ignored for 5.8 to fit positional splits
#bottom of workibg№№##№######$##
###№####
#######
def log_all_stats_shadow(game, config, sh):
    """Cumulative Tracker: Uses forced value-input and robust sheet discovery."""
    try:
        api_clubs = game.get('clubs', {})
        match_updates = {"Master Totals Skaters": {}, "Master Totals Goalies": {}}

        # 1. Map data from API
        for cid, players in game['players'].items():
            t_name = api_clubs.get(cid, {}).get('details', {}).get('name') or config.get("team_ids", {}).get(str(cid), f"Team {cid}")
            for pid, p in players.items():
                p_id = str(pid)
                is_goalie = str(p.get('position')) == "0" or int(p.get('glsaves', 0)) > 0
                target = "Master Totals Goalies" if is_goalie else "Master Totals Skaters"
                
                match_updates[target][p_id] = {
                    "Player ID": p_id, "Player Name": p.get('playername', 'Unknown'),
                    "Team Name": t_name, "Games Played": 1
                }
                match_updates[target][p_id].update(p)

        # 2. Update Sheets
        for sheet_name, new_data in match_updates.items():
            if not new_data: continue

            # Re-fetch worksheet list to prevent "missing sheet" errors
            ws_list = [w.title for w in sh.worksheets()]
            if sheet_name not in ws_list:
                print(f"DEBUG: Creating {sheet_name}...")
                ws = sh.add_worksheet(sheet_name, 2000, 100)
            else:
                ws = sh.worksheet(sheet_name)

            # Get current data
            raw_rows = ws.get_all_values()
            
            # Robust Header Detection: Use first player keys if sheet is empty or has no text
            if not raw_rows or not any(raw_rows[0]):
                headers = list(next(iter(new_data.values())).keys())
                sheet_dict = {}
            else:
                headers = raw_rows[0]
                # Map existing rows by ID (Column 0)
                sheet_dict = {str(r[0]): r for r in raw_rows[1:] if r}

            # Merge
            for p_id, p_stats in new_data.items():
                if p_id in sheet_dict:
                    row = sheet_dict[p_id]
                    for i, h in enumerate(headers):
                        if h not in ["Player Name", "Team Name", "Player ID", "Position"]:
                            try:
                                old = int(float(str(row[i]))) if i < len(row) and row[i] else 0
                                add = int(float(str(p_stats.get(h, 0))))
                                row[i] = str(old + add)
                            except: pass
                else:
                    sheet_dict[p_id] = [str(p_stats.get(h, "0")) for h in headers]

            # 3. THE "FORCE" PUSH
            final_matrix = [headers] + list(sheet_dict.values())
            
            # We use update() with the specific value_input_option
            # This is what usually fixes the "empty sheet" bug
            ws.clear()
            ws.update('A1', final_matrix, value_input_option='USER_ENTERED')
            print(f"SUCCESS: {sheet_name} now has {len(final_matrix)} total rows.")

    except Exception as e:
        print(f"SHADOW ERROR: {e}")
def get_master_stats_data():
    """Reads all data from Master Skater and Goalie tabs."""
    sh = get_sheet()
    if not sh: return {}
    
    combined_data = {}
    # Iterate through both Master tabs
    for tab_name in ["Master Totals Skaters", "Master Totals Goalies"]:
        try:
            ws = sh.worksheet(tab_name)
            records = ws.get_all_records()
            for row in records:
                name = row.get("Player Name")
                if name:
                    # Ensure numeric values for math
                    for key in row:
                        if key not in ["Player Name", "Team Name", "Position"]:
                            try: row[key] = int(float(row[key]))
                            except: row[key] = 0
                    
                    # Calculate extra stats on the fly
                    row['Points'] = row.get('skgoals', 0) + row.get('skassists', 0)
                    fo_win = row.get('skfowon', 0)
                    fo_lost = row.get('skfolost', 0)
                    total_fo = fo_win + fo_lost
                    row['FO%'] = round((fo_win / total_fo) * 100, 1) if total_fo > 0 else 0
                    
                    combined_data[name] = row
        except Exception as e:
            print(f"Error reading {tab_name}: {e}")
            continue
    return combined_data
