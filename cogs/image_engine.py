# ============================================================
#  OS4 League Bot — image_engine.py
#  Version: 1.8.0
#  A NEW COG — replaces image generators in utils.py at runtime.
#  NOTHING in utils.py or any existing cog is touched.
#
#  Changelog:
#    v1.0.0 - Initial release. Professional branded image engine.
#    v1.1.0 - EA API numeric-as-string fix via _safe_int().
#    v1.2.0 - Non-ASCII font fallback fix via _safe_str().
#    v1.3.0 - Truncated position names fix via _shorten_pos().
#    v1.4.0 - Star symbols replaced with text alternatives.
#    v1.5.0 - Team logos added inline (ESPN CDN).
#    v1.6.0 - Replaced ESPN CDN with local ./logos/ disk loading.
#    v1.7.0 - Standings patch name fix. Game report logo overlap
#             fix. Roster positional columns added.
#    v1.8.0 - Roster overhaul: real positional GP, two teams side by side.
#    v1.8.1 - Roster fix: G column no longer clipped. Center divider
#             is now a solid 4px blue accent line spanning full row height.
# ============================================================

VERSION  = "3.0.3"
COG_NAME = "ImageEngine"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading")

import io
import os
import utils
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(utils.__file__))

# ════════════════════════════════════════════════════════════
#  BRANDING HELPER
#  Reads league_name and bot_name from utils (patched by
#  branding.py at load time). Falls back to defaults if
#  branding.py isn't loaded yet.
# ════════════════════════════════════════════════════════════

def _league() -> str:
    try:    return utils.get_league_name()
    except: return utils.load_config().get("league_name", "League")

def _botname() -> str:
    try:    return utils.get_bot_name()
    except: return utils.load_config().get("bot_name", "Stats Bot")

def _footer(section: str) -> str:
    """Returns a standard footer string: 'BotName  •  Section  •  Image Engine vX.Y.Z'"""
    return f"{_botname()}  •  {section}  •  Image Engine v{VERSION}"

def _title(text: str) -> str:
    """Prefix a title with the league name: 'LEAGUE — TEXT'"""
    return f"{_league().upper()} — {text}"

# ════════════════════════════════════════════════════════════
#  BRAND PALETTE
# ════════════════════════════════════════════════════════════
B = {
    # Base canvas
    "bg":         "#0a0c0f",   # near-black, slightly warm
    "panel":      "#12161c",   # card surface
    "panel2":     "#181d25",   # slightly lighter panels
    "dark":       "#060709",   # deepest black for title bars

    # Borders & rows
    "border":     "#252b35",
    "header_row": "#181d25",
    "row_main":   "#0a0c0f",
    "row_alt":    "#10141a",

    # Brand — gold/amber accent
    "accent":     "#C9A84C",   # warm gold (primary brand)
    "accent2":    "#8B6914",   # darker gold for dividers/bars

    # Semantic
    "win":        "#4ade80",   # clean green
    "loss":       "#f87171",   # soft red
    "dnf":        "#fb923c",   # orange

    # Metals
    "gold":       "#C9A84C",
    "silver":     "#9ca3af",
    "bronze":     "#b07040",

    # Text
    "white":      "#f0f2f5",
    "grey":       "#6b7280",
    "grey2":      "#9ca3af",
}

# ════════════════════════════════════════════════════════════
#  TRANSPARENT PANEL COLORS (RGBA)
#  Used for background fills so the background image shows through.
#  Thin lines and accents keep opaque hex colors from B.
# ════════════════════════════════════════════════════════════

BA = {
    "dark":       (6,   7,   9,   185),  # title/header bars
    "panel":      (18,  22,  28,  150),  # card surfaces
    "panel2":     (24,  29,  37,  140),  # slightly lighter panels
    "header_row": (24,  29,  37,  140),  # table header rows
    "row_main":   (10,  12,  15,   90),  # primary rows — most transparent
    "row_alt":    (16,  20,  26,  110),  # alternating rows
}

def _fill_rect(draw_or_img, xy, fill_rgba):
    """
    Draw a semi-transparent rectangle onto an RGBA image.
    Accepts either a draw context or an image directly.
    Returns a fresh draw context (required after alpha_composite).
    """
    if isinstance(draw_or_img, ImageDraw.ImageDraw):
        img = draw_or_img._image
    else:
        img = draw_or_img
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(xy, fill=fill_rgba)
    composited = Image.alpha_composite(img, layer)
    img.paste(composited)
    return ImageDraw.Draw(img)


# ════════════════════════════════════════════════════════════
#  FONTS
# ════════════════════════════════════════════════════════════

def _font(size):
    try:
        return ImageFont.truetype(os.path.join(BASE_DIR, "font.ttf"), size)
    except:
        return ImageFont.load_default()

FONTS = {
    "title":  _font(68),
    "h1":     _font(78),
    "h2":     _font(48),
    "h3":     _font(36),
    "header": _font(38),
    "row":    _font(30),
    "small":  _font(22),
    "score":  _font(88),
    "team":   _font(50),
    "lbl":    _font(24),
    "val":    _font(40),
    "badge":  _font(26),
}

# ════════════════════════════════════════════════════════════
#  SAFE CAST HELPERS
# ════════════════════════════════════════════════════════════

def _safe_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default

def _safe_str(s):
    if not isinstance(s, str):
        s = str(s)
    return s.encode("ascii", errors="ignore").decode("ascii").strip()

# EA position string -> display bucket
# All wing positions map to W, all d map to D, etc.
_POS_BUCKET = {
    # EA API values
    "leftWing":    "W",
    "rightWing":   "W",
    "center":      "C",
    "defenseman":  "D",
    "defense":     "D",   # sheet often stores this form
    "goalie":      "G",
    # Short forms in sheet
    "lw":  "W",
    "rw":  "W",
    "lef": "W",
    "rig": "W",
    "c":   "C",
    "cen": "C",
    "d":   "D",
    "def": "D",
    "ld":  "D",
    "rd":  "D",
    "g":   "G",
    "goaltender": "G",
    "0":   "G",   # EA sometimes sends position as "0" for goalie
}

def _pos_bucket(pos_raw: str) -> str:
    """Map any EA position string to C / W / D / G. Defaults to W."""
    key = str(pos_raw).strip().lower()
    # Catch all variations of defense/defence immediately
    if "defense" in key or "defence" in key:
        return "D"
    return _POS_BUCKET.get(key, "W")

_POS_SHORT = {
    "center":      "C",
    "left wing":   "LW",
    "right wing":  "RW",
    "defense":     "D",
    "defenseman":  "D",
    "goalie":      "G",
    "goaltender":  "G",
    "forward":     "F",
    "leftWing":    "LW",
    "rightWing":   "RW",
    "lef":         "LW",
    "rig":         "RW",
    "def":         "D",
    "cen":         "C",
}

def _shorten_pos(pos):
    p = str(pos).strip().lower()
    # Safely return "D" for any defense string
    if "defense" in p or "defence" in p:
        return "D"
    return _POS_SHORT.get(p, _POS_SHORT.get(str(pos).strip(), str(pos)[:3]))

# ════════════════════════════════════════════════════════════
#  POSITIONAL ROSTER DATA
#  Reads Player Stats sheet and returns per-player positional GP.
#  {tid: {player_name: {"total": n, "C": n, "W": n, "D": n, "G": n}}}
# ════════════════════════════════════════════════════════════

def _get_roster_positional_data(config: dict) -> dict:
    """
    Reads the Player Stats sheet directly.
    Returns {team_id: {player_name: {total, C, W, D, G}}}.
    Falls back to empty dicts on any error.
    """
    rosters = {}
    try:
        sh = utils.get_sheet()
        if not sh:
            return rosters
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Match ID", "Username"])
        if h_idx == -1:
            return rosters

        def _idx(col):
            try:    return h.index(col)
            except: return -1

        i_name = _idx("Username")
        i_team = _idx("Team Name")   # new schema
        i_user = _idx("Username")
        i_pos  = _idx("position")    # new schema (lowercase)

        if i_name == -1:
            return rosters

        for r in rows[h_idx + 1:]:
            if len(r) <= i_name:
                continue
            # Skip stub rows
            uval = str(r[i_user]).strip() if i_user != -1 and i_user < len(r) else ""
            if "[DNF-PENDING]" in uval or "[MERGED" in uval:
                continue

            name  = str(r[i_name]).strip()
            cid   = str(r[i_team]).strip() if i_team != -1 and i_team < len(r) else ""
            if not name or not cid:
                continue

            pos_raw = str(r[i_pos]).strip() if i_pos != -1 and i_pos < len(r) else "W"
            bucket  = _pos_bucket(pos_raw)

            if cid not in rosters:
                rosters[cid] = {}
            if name not in rosters[cid]:
                rosters[cid][name] = {"total": 0, "C": 0, "W": 0, "D": 0, "G": 0}

            rosters[cid][name]["total"] += 1
            rosters[cid][name][bucket]  += 1

    except Exception as e:
        print(f"[{COG_NAME}] _get_roster_positional_data error: {e}")

    return rosters


# ════════════════════════════════════════════════════════════
#  LOGO HELPER — local disk, safe inside run_in_executor
# ════════════════════════════════════════════════════════════

def _get_logo(team_name: str, size: int = 48) -> "Image.Image | None":
    if not team_name:
        return None
    try:
        from cogs.team_logos import get_team_logo_image
        return get_team_logo_image(team_name, size=size)
    except Exception as e:
        print(f"[{COG_NAME}] _get_logo('{team_name}'): {e}")
        return None

def _paste_logo(img, logo, x: int, y: int):
    if logo is None:
        return
    try:
        img.paste(logo.convert("RGBA"), (x, y), logo.convert("RGBA"))
    except Exception as e:
        print(f"[{COG_NAME}] paste logo: {e}")

# ════════════════════════════════════════════════════════════
#  CANVAS + DRAWING PRIMITIVES
# ════════════════════════════════════════════════════════════

def _base(width, height):
    """
    Creates RGBA base canvas. Background stays visible through
    semi-transparent BA panel fills.
    """
    try:
        bg = Image.open(os.path.join(BASE_DIR, "background.png")).resize((width, height)).convert("RGBA")
        overlay = Image.new("RGBA", bg.size, (6, 7, 9, 50))
        img = Image.alpha_composite(bg, overlay)
        return img, ImageDraw.Draw(img)
    except:
        pass

    img  = Image.new("RGBA", (width, height), color=(10, 12, 15, 255))
    draw = ImageDraw.Draw(img)
    for i in range(0, height, 2):
        alpha = int(6 * (1 - i / height))
        c = (10 + alpha, 14 + alpha, 20 + alpha, 255)
        draw.line([(0, i), (width, i)], fill=c)
    cx, cy, r = width // 2, height // 2, min(width, height) // 3
    for ring in range(r, r + 3):
        draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring),
                     outline=(20, 25, 32, 255), width=1)
    for ly in [height // 3, 2 * height // 3]:
        draw.rectangle((0, ly, width, ly + 1), fill=(14, 20, 30, 255))
    return img, ImageDraw.Draw(img)


def _draw_title_bar(draw, width, height, title, subtitle=""):
    # Clean dark header with left gold accent bar + bottom divider
    draw = _fill_rect(draw, (0, 0, width, height), BA["dark"])
    # Left gold accent bar (thicker = more premium)
    draw.rectangle((0, 0, 6, height), fill=B["accent"])
    # Title text
    draw.text((28, 14), title, font=FONTS["title"], fill=B["white"])
    if subtitle:
        draw.text((32, 88), subtitle, font=FONTS["small"], fill=B["grey"])
    # Thin gold bottom line
    draw.rectangle((0, height - 2, width, height), fill=B["accent"])

def _draw_section_header(draw, width, y, label, color=None):
    color = color or B["accent"]
    H = 52   # h3 is 36px — needs at least 36 + 8 top + 8 bottom = 52
    draw = _fill_rect(draw, (0, y, width, y + H), BA["panel2"])
    draw.rectangle((0, y, 4, y + H), fill=color)
    draw.rectangle((0, y, width, y + 1), fill=B["border"])
    draw.rectangle((0, y + H - 1, width, y + H), fill=B["accent2"])
    draw.text((22, y + 8), label, font=FONTS["h3"], fill=color)
    return y + H

def _draw_section_header_with_logo(img, draw, width, y, label, team_name,
                                    logo_size=44, color=None, x_offset=0):
    color = color or B["accent"]
    H = 64   # tall enough to fully contain h2 (48px) with padding
    draw = _fill_rect(draw, (x_offset, y, x_offset + width, y + H), BA["panel2"])
    draw.rectangle((x_offset, y, x_offset + 4, y + H), fill=color)
    draw.rectangle((x_offset, y + H - 1, x_offset + width, y + H), fill=B["accent2"])
    draw.text((x_offset + 20, y + 8), label, font=FONTS["h2"], fill=color)
    logo = _get_logo(team_name, size=logo_size)
    if logo:
        _paste_logo(img, logo, x_offset + width - logo_size - 20, y + (H - logo_size) // 2)
    return y + H

def _draw_table_header(draw, xs, labels, y, row_height=48, color=None, font=None):
    draw = _fill_rect(draw, (0, y, 99999, y + row_height), BA["header_row"])
    # Single thin gold bottom rule
    draw.rectangle((0, y + row_height - 1, 99999, y + row_height), fill=B["accent2"])
    fnt = font or FONTS["header"]
    for i, lbl in enumerate(labels):
        draw.text((xs[i], y + (row_height - fnt.size) // 2 - 2),
                  lbl, font=fnt, fill=color or B["accent"])
    return y + row_height

def _draw_table_row(draw, xs, values, y, row_height=44, alt=False, fills=None):
    bg = BA["row_alt"] if alt else BA["row_main"]
    draw = _fill_rect(draw, (0, y, 99999, y + row_height), bg)
    for i, val in enumerate(values):
        fill = (fills[i] if fills and i < len(fills) else B["grey2"])
        draw.text((xs[i], y + 7), str(val), font=FONTS["row"], fill=fill)
    return y + row_height

def _draw_stat_pill(draw, cx, y, label, value, color=None):
    color = color or B["accent"]
    lw = draw.textlength(label, font=FONTS["lbl"])
    vw = draw.textlength(str(value), font=FONTS["val"])
    box_w = max(lw, vw) + 28
    # Card background with left border
    draw = _fill_rect(draw, (cx - box_w//2, y, cx + box_w//2, y + 74), BA["panel"])
    draw.rectangle((cx - box_w//2, y, cx + box_w//2, y + 3), fill=color)
    draw.rectangle((cx - box_w//2, y + 71, cx + box_w//2, y + 74), fill=B["border"])
    draw.text((cx - lw//2, y + 7), label, font=FONTS["lbl"], fill=B["grey"])
    draw.text((cx - vw//2, y + 30), str(value), font=FONTS["val"], fill=B["white"])

def _draw_footer(draw, width, y, text):
    draw.rectangle((0, y, width, y + 1), fill=B["accent2"])
    draw = _fill_rect(draw, (0, y + 1, width, y + 38), BA["dark"])
    fw = draw.textlength(text, font=FONTS["small"])
    draw.text(((width - fw) / 2, y + 10), text, font=FONTS["small"], fill=B["grey"])
    return y + 38

# ════════════════════════════════════════════════════════════
#  ROSTER PANEL HELPER
#  Draws one team's roster panel into the image at x_offset.
#  panel_width = how wide the panel is.
#  Returns the lowest y reached.
# ════════════════════════════════════════════════════════════

def _draw_roster_panel(img, draw, players_data, tname, x_offset, panel_width,
                        start_y, row_height=42):
    """
    players_data: {player_name: {total, C, W, D, G}}
    Draws team header + table within x_offset..x_offset+panel_width.
    Returns y after last row.
    """
    HEADER_H = 56
    COL_H    = 44
    PAD      = 10

    # Section header
    color = B["accent"]
    draw = _fill_rect(draw, (x_offset, start_y, x_offset + panel_width, start_y + HEADER_H), BA["panel2"])
    draw.rectangle((x_offset, start_y, x_offset + 6, start_y + HEADER_H), fill=color)

    # Team name — truncate to fit
    label = _safe_str(tname).upper()
    draw.text((x_offset + 24, start_y + 10), label, font=FONTS["h3"], fill=color)

    # Logo
    logo = _get_logo(tname, size=40)
    if logo:
        _paste_logo(img, logo, x_offset + panel_width - 60, start_y + 8)

    y = start_y + HEADER_H

    # Column x positions relative to x_offset
    # Gamertag | GP | C | W | D | G
    # Use fixed pixel widths so G is never clipped
    DIVIDER   = 4          # gap between panels (drawn separately)
    usable_w  = panel_width - PAD * 2 - DIVIDER
    name_w    = int(usable_w * 0.46)
    gp_w      = int(usable_w * 0.12)
    stat_w    = int(usable_w * 0.10)  # C, W, D, G each get 10%

    xs = [
        x_offset + PAD,                               # Gamertag
        x_offset + PAD + name_w,                      # GP
        x_offset + PAD + name_w + gp_w,               # C
        x_offset + PAD + name_w + gp_w + stat_w,      # W
        x_offset + PAD + name_w + gp_w + stat_w * 2,  # D
        x_offset + PAD + name_w + gp_w + stat_w * 3,  # G
    ]
    hdrs = ["Gamertag", "GP", "C", "W", "D", "G"]

    # Column header row
    draw = _fill_rect(draw, (x_offset, y, x_offset + panel_width, y + COL_H), BA["header_row"])
    draw.rectangle((x_offset, y + COL_H - 2, x_offset + panel_width, y + COL_H),
                    fill=B["accent2"])
    for i, lbl in enumerate(hdrs):
        draw.text((xs[i], y + 6), lbl, font=FONTS["badge"], fill=B["accent"])
    y += COL_H

    # Sort by total GP descending
    sorted_players = sorted(players_data.items(),
                            key=lambda x: x[1]["total"] if isinstance(x[1], dict) else x[1],
                            reverse=True)

    for alt_i, (pname, pdata) in enumerate(sorted_players):
        bg = BA["row_alt"] if alt_i % 2 == 1 else BA["row_main"]
        draw = _fill_rect(draw, (x_offset, y, x_offset + panel_width, y + row_height), bg)

        # Handle both dict {total,C,W,D,G} and plain int (fallback)
        if isinstance(pdata, dict):
            total = pdata.get("total", 0)
            c_gp  = pdata.get("C", 0)
            w_gp  = pdata.get("W", 0)
            d_gp  = pdata.get("D", 0)
            g_gp  = pdata.get("G", 0)
        else:
            total = int(pdata)
            c_gp = w_gp = d_gp = g_gp = 0

        def _fmt(v):
            return str(v) if v > 0 else "-"

        vals  = [_safe_str(pname[:24]), str(total),
                 _fmt(c_gp), _fmt(w_gp), _fmt(d_gp), _fmt(g_gp)]
        fills = [B["white"], B["grey2"],
                 B["accent"], B["accent"], B["win"], B["gold"]]
        for i in range(2, 6):
            if vals[i] == "-":
                fills[i] = B["grey"]

        for i, (v, f) in enumerate(zip(vals, fills)):
            draw.text((xs[i], y + 7), v, font=FONTS["row"], fill=f)

        y += row_height

    # Bottom divider
    draw.rectangle((x_offset + 10, y, x_offset + panel_width - 10, y + 2), fill=B["border"])
    y += 16

    return y


# ════════════════════════════════════════════════════════════
#  ROSTER IMAGE  — two teams side by side
# ════════════════════════════════════════════════════════════

def _generate_roster_image(roster_data, config):
    """
    roster_data: {tid: {player_name: gp}}  — from utils (fallback)
    Fetches real positional data from Player Stats sheet and merges.
    Teams are laid out two per row, side by side.
    """
    # Fetch real positional GP from sheet
    try:
        positional = _get_roster_positional_data(config)
    except Exception as e:
        print(f"[{COG_NAME}] positional fetch error: {e}")
        positional = {}

    # Use positional data directly (keyed by team name from sheet).
    # Only fall back to roster_data if positional came back empty.
    if positional:
        teams = [(tname, players) for tname, players in positional.items() if players]
    else:
        teams = [(tid, {n: {"total": gp, "C":0,"W":0,"D":0,"G":0}
                         for n, gp in players.items()})
                  for tid, players in roster_data.items() if players]

    team_names = config.get("team_ids", {})

    # Layout: 2 panels per row
    PANELS_PER_ROW = 2
    TOTAL_WIDTH    = 1800
    TITLE_H        = 120
    PANEL_W        = TOTAL_WIDTH // PANELS_PER_ROW
    ROW_H          = 42

    # Estimate height: each team needs header(56) + col_header(44) + rows*ROW_H + divider(18)
    def _team_height(players):
        return 56 + 44 + len(players) * ROW_H + 18

    # Group teams into rows of 2
    team_rows = [teams[i:i+PANELS_PER_ROW] for i in range(0, len(teams), PANELS_PER_ROW)]

    total_content_h = sum(
        max(_team_height(players) for _, players in row)
        for row in team_rows
    )
    HEIGHT = TITLE_H + total_content_h + 60
    HEIGHT = max(HEIGHT, 600)

    img, draw = _base(TOTAL_WIDTH, HEIGHT)
    _draw_title_bar(draw, TOTAL_WIDTH, TITLE_H, _league().upper() + " ROSTERS",
                    subtitle="Season Active Roster  •  GP by Position")

    y = TITLE_H

    for row_teams in team_rows:
        # Find the tallest panel in this row to advance y uniformly
        row_heights = []
        for col_i, (tid, players) in enumerate(row_teams):
            tname    = str(tid)  # tid is already team name in new schema
            x_offset = col_i * PANEL_W
            bottom_y = _draw_roster_panel(img, draw, players, tname,
                                           x_offset, PANEL_W, y, row_height=ROW_H)
            row_heights.append(bottom_y)

        # Draw vertical blue divider spanning full height of this row
        div_x = PANEL_W - 2
        draw.rectangle((div_x, y, div_x + 4, max(row_heights)), fill=B["accent2"])

        y = max(row_heights)

    y = _draw_footer(draw, TOTAL_WIDTH, y + 4,
                     _footer("Roster"))
    img = img.crop((0, 0, TOTAL_WIDTH, y))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  PLAYER CARD
# ════════════════════════════════════════════════════════════

def _generate_player_card(name, stats, logs, team_name):
    # Resolve team name if passed the hardcoded "Player" fallback
    if not team_name or team_name.lower() in ("player", "unknown", ""):
        try:
            sh = utils.get_sheet()
            if sh:
                ws   = sh.worksheet("Player Stats")
                rows = ws.get_all_values()
                h_idx, h = utils.find_header_row(rows, ["Username", "Team ID"])
                if h_idx != -1:
                    i_usr = h.index("Username")
                    i_tid = h.index("Team ID")
                    name_lower = name.strip().lower()
                    for r in rows[h_idx + 1:]:
                        if len(r) > max(i_usr, i_tid):
                            if str(r[i_usr]).strip().lower() == name_lower:
                                tid = str(r[i_tid]).strip()
                                cfg = utils.load_config()
                                team_name = cfg.get("team_ids", {}).get(tid, tid)
                                break
        except Exception as e:
            print(f"[{COG_NAME}] player_card team lookup failed: {e}")

    tot       = stats.get("Total", {})
    is_goalie = tot.get("Main Position") == "Goalie"

    # Fetch extended goalie stats from Master Totals Goalies
    goalie_master = {}
    if is_goalie:
        try:
            sh = utils.get_sheet()
            if sh:
                ws   = sh.worksheet("Master Totals Goalies")
                rows = ws.get_all_values()
                if rows:
                    hdr = [c.strip() for c in rows[0]]
                    name_lower = name.strip().lower()
                    pname_col = hdr.index("playername") if "playername" in hdr else -1
                    for r in rows[1:]:
                        if pname_col == -1 or pname_col >= len(r): continue
                        if str(r[pname_col]).strip().lower() != name_lower: continue
                        def _gv(k):
                            if k in hdr:
                                try: return int(float(r[hdr.index(k)]))
                                except: return 0
                            return 0
                        goalie_master = {
                            "brk_saves":   _gv("glbrksaves"),
                            "brk_shots":   _gv("glbrkshots"),
                            "pen_saves":   _gv("glpensaves"),
                            "pen_shots":   _gv("glpenshots"),
                            "pokechecks":  _gv("glpokechecks"),
                            "pkclear":     _gv("glpkclearzone"),
                            "dzone_saves": _gv("gldsaves"),
                            "so_periods":  _gv("glsoperiods"),
                        }
                        break
        except Exception as e:
            print(f"[{COG_NAME}] goalie master lookup error: {e}")

    WIDTH = 1900
    positions_present = [p for p in ["Forward","Defense","Goalie"]
                         if stats.get(p, {}).get("GP", 0) > 0]
    HEIGHT = 130 + 120 + 110 + 60 + len(positions_present) * 300 + (100 if goalie_master else 0) + 80
    HEIGHT = max(HEIGHT, 900)

    img, draw = _base(WIDTH, HEIGHT)
    _draw_title_bar(draw, WIDTH, 120, _safe_str(name[:32]),
                    subtitle=f"\u25c8  {_safe_str(team_name).upper()}")
    logo = _get_logo(team_name, size=90)
    if logo:
        _paste_logo(img, logo, WIDTH - 110, 15)

    y = 130

    # ── CAREER TOTALS
    draw.text((30, y), "CAREER TOTALS", font=FONTS["h2"], fill=B["white"])
    draw.rectangle((30, y + 52, WIDTH - 30, y + 54), fill=B["border"])
    y += 64

    if is_goalie:
        sv = tot.get("Sv", 0); ga = tot.get("GA", 0); gp = tot.get("GP", 0)
        sa = sv + ga
        svp = f"{sv/sa:.3f}" if sa > 0 else "0.000"
        gaa = f"{ga/gp:.2f}" if gp > 0 else "0.00"
        row1 = [("GP",gp),("SA",sa),("SV",sv),("GA",ga),("SV%",svp),("GAA",gaa),
                ("AST",tot.get("A",0)),("PTS",tot.get("P",0))]
        row2 = []
        if goalie_master:
            bsv = goalie_master["brk_saves"]; bsh = goalie_master["brk_shots"]
            psv = goalie_master["pen_saves"]; psh = goalie_master["pen_shots"]
            row2 = [
                ("BRK SV",bsv),("BRK SA",bsh),
                ("BRK SV%",f"{bsv/bsh:.3f}" if bsh>0 else "-.---"),
                ("PEN SV",psv),("PEN SA",psh),
                ("PEN SV%",f"{psv/psh:.3f}" if psh>0 else "-.---"),
                ("POKE",goalie_master["pokechecks"]),
                ("DZ SV",goalie_master["dzone_saves"]),
                ("PK CLR",goalie_master["pkclear"]),
                ("SO PER",goalie_master["so_periods"]),
            ]
    else:
        row1 = [("GP",tot.get("GP",0)),("G",tot.get("G",0)),("A",tot.get("A",0)),
                ("PTS",tot.get("P",0)),("+/-",tot.get("+/-",0)),("HITS",tot.get("Hits",0)),
                ("SHOTS",tot.get("S",0)),("PIM",tot.get("PIM",0))]
        row2 = [("TK",tot.get("TK",0)),("GV",tot.get("GV",0)),("INT",tot.get("INT",0)),
                ("BS",tot.get("BS",0)),("DEF",tot.get("DEF",0)),
                ("PPG",tot.get("PPG",0)),("SHG",tot.get("SHG",0)),
                ("FO%",f"{tot.get('FO%',0.0):.1f}%"),
                ("PASS%",f"{tot.get('Pass%',0.0):.1f}%")]

    def _draw_pill_row(items, start_y):
        spacing = (WIDTH - 60) // len(items)
        cx = 60 + spacing // 2
        for lbl, val in items:
            color = (B["win"]  if lbl in ("PTS","SV%","BRK SV%","PEN SV%") else
                     B["loss"] if lbl in ("GV","GA") else B["accent"])
            _draw_stat_pill(draw, cx, start_y, lbl, str(val), color=color)
            cx += spacing
        return start_y + 88

    y = _draw_pill_row(row1, y)
    if row2:
        y = _draw_pill_row(row2, y + 4)
    y += 18

    # ── POSITIONAL SPLITS
    y = _draw_section_header(draw, WIDTH, y, "POSITIONAL SPLITS")
    y += 8

    def _cols(n):
        step = (WIDTH - 80) // n
        return [40 + i * step for i in range(n)]

    for pos in ["Forward", "Defense", "Goalie"]:
        p = stats.get(pos, {})
        if not p.get("GP", 0):
            continue

        pos_color = {"Forward":B["win"],"Defense":B["accent"],"Goalie":B["gold"]}.get(pos,B["white"])
        draw = _fill_rect(draw, (0, y, WIDTH, y + 44), BA["panel2"])
        draw.rectangle((0, y, 6, y + 44), fill=pos_color)
        draw.text((20, y + 7), pos.upper(), font=FONTS["header"], fill=pos_color)
        y += 48

        if pos == "Goalie":
            sv2 = p.get("Sv",0); ga2 = p.get("GA",0)
            sa2 = p.get("SA", sv2+ga2); gp2 = p.get("GP",0)
            svp2 = f"{sv2/sa2:.3f}" if sa2>0 else "0.000"
            gaa2 = f"{ga2/gp2:.2f}" if gp2>0 else "0.00"
            hdrs1 = ["GP","SA","SV","GA","SV%","GAA","AST","PTS"]
            vals1 = [gp2,sa2,sv2,ga2,svp2,gaa2,p.get("A",0),p.get("P",0)]
            fills1 = [B["grey2"],B["grey2"],B["win"],B["loss"],B["gold"],B["dnf"],B["grey2"],B["win"]]
            y = _draw_table_header(draw, _cols(8), hdrs1, y, row_height=44, font=FONTS["small"])
            y = _draw_table_row(draw, _cols(8), vals1, y, row_height=44, fills=fills1)
            if goalie_master:
                y += 4
                bsv = goalie_master["brk_saves"]; bsh = goalie_master["brk_shots"]
                psv = goalie_master["pen_saves"]; psh = goalie_master["pen_shots"]
                hdrs2 = ["BRK SV","BRK SA","BRK SV%","PEN SV","PEN SA","PEN SV%","POKE","DZ SV","PK CLR","SO PER"]
                vals2 = [bsv,bsh,
                         f"{bsv/bsh:.3f}" if bsh>0 else "-.---",
                         psv,psh,
                         f"{psv/psh:.3f}" if psh>0 else "-.---",
                         goalie_master["pokechecks"],
                         goalie_master["dzone_saves"],
                         goalie_master["pkclear"],
                         goalie_master["so_periods"]]
                fills2 = [B["win"],B["grey2"],B["gold"],B["win"],B["grey2"],B["gold"],
                          B["accent"],B["accent"],B["grey2"],B["grey2"]]
                y = _draw_table_header(draw, _cols(10), hdrs2, y, row_height=44, font=FONTS["small"])
                y = _draw_table_row(draw, _cols(10), vals2, y, row_height=44, fills=fills2)
        else:
            pm   = p.get("+/-", 0)
            pm_c = B["win"] if pm > 0 else (B["loss"] if pm < 0 else B["grey2"])
            hdrs1 = ["GP","G","A","PTS","+/-","HITS","S","TK","GV","INT","BS","DEF","PIM"]
            vals1 = [p.get("GP",0),p.get("G",0),p.get("A",0),p.get("P",0),
                     pm,p.get("Hits",0),p.get("S",0),
                     p.get("TK",0),p.get("GV",0),p.get("INT",0),
                     p.get("BS",0),p.get("DEF",0),p.get("PIM",0)]
            fills1 = [B["grey2"],B["win"],B["win"],B["win"],
                      pm_c,B["grey2"],B["grey2"],
                      B["accent"],B["loss"],B["accent"],
                      B["grey2"],B["grey2"],B["grey2"]]
            y = _draw_table_header(draw, _cols(13), hdrs1, y, row_height=44, font=FONTS["small"])
            y = _draw_table_row(draw, _cols(13), vals1, y, row_height=44, fills=fills1)
            y += 4
            fo_pct  = f"{p.get('FO%',0.0):.1f}%"
            pas_pct = f"{p.get('Pass%',0.0):.1f}%"
            poss    = p.get("Poss", 0)
            hdrs2 = ["PPG","SHG","PD","FOW","FOL","FO%","PASS","PASS%","SA","SAUC","POSS"]
            vals2 = [p.get("PPG",0),p.get("SHG",0),p.get("PD",0),
                     p.get("FOW",0),p.get("FOL",0),fo_pct,
                     p.get("Pass",0),pas_pct,
                     p.get("ShotAtt",0),p.get("Sauc",0),
                     f"{poss//60}:{poss%60:02d}"]
            fills2 = [B["gold"],B["gold"],B["grey2"],
                      B["accent"],B["grey2"],B["accent"],
                      B["grey2"],B["accent"],
                      B["grey2"],B["grey2"],B["grey2"]]
            y = _draw_table_header(draw, _cols(11), hdrs2, y, row_height=44, font=FONTS["small"])
            y = _draw_table_row(draw, _cols(11), vals2, y, row_height=44, fills=fills2)

        y += 20

    # ── RECENT GAMES
    if logs:
        y = _draw_section_header(draw, WIDTH, y + 4, "RECENT GAMES")
        y += 8

        is_goalie_log = any(
            'goalie' in str(g.get('position','')).lower() or g.get('saves',0) > 0
            for g in logs[:3]
        )

        if is_goalie_log:
            log_hdrs = ["DATE","OPPONENT","RES","POS","SA","SV","GA","SV%","TOI"]
            log_cols = _cols(9)
        else:
            log_hdrs = ["DATE","OPPONENT","RES","POS","G","A","PTS","+/-","HITS","S","TOI"]
            log_cols = _cols(11)

        y = _draw_table_header(draw, log_cols, log_hdrs, y, row_height=40, font=FONTS["small"])

        for i, g in enumerate(logs):
            sv    = g.get("saves", 0); ga_g = g.get("ga", 0)
            sa    = sv + ga_g
            toi_s = g.get("toiseconds", 0)
            toi_str = f"{toi_s//60}:{toi_s%60:02d}"
            pos_str = _shorten_pos(g.get("position",""))
            pm    = g.get("plus_minus", 0)
            pm_c  = B["win"] if pm > 0 else (B["loss"] if pm < 0 else B["grey2"])
            res   = g.get("result", "")
            res_c = (B["win"] if res in ("W","OTW","W-FF") else
                     B["loss"] if res in ("L","OTL","L-FF") else B["dnf"])
            opp   = _safe_str(g.get("opponent","")[:18])

            if is_goalie_log:
                svpct = f"{sv/sa:.3f}" if sa > 0 else "-.---"
                vals  = [g.get("date","")[:10], opp, res, pos_str,
                         sa, sv, ga_g, svpct, toi_str]
                fills = [B["grey2"],B["white"],res_c,B["grey2"],
                         B["grey2"],B["win"],B["loss"],B["gold"],B["grey2"]]
            else:
                pts  = g.get("points", g.get("goals",0)+g.get("assists",0))
                vals = [g.get("date","")[:10], opp, res, pos_str,
                        g.get("goals",0), g.get("assists",0), pts,
                        pm, g.get("hits",0), g.get("shots",0), toi_str]
                fills = [B["grey2"],B["white"],res_c,B["grey2"],
                         B["win"],B["win"],B["win"],
                         pm_c,B["grey2"],B["grey2"],B["grey2"]]

            y = _draw_table_row(draw, log_cols, vals, y, row_height=40, alt=i%2==1, fills=fills)

        y += 8

    y = _draw_footer(draw, WIDTH, y + 6, _footer("Player Stats"))
    img = img.crop((0, 0, WIDTH, y))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  EXTENDED SEASON STATS
#  Enriches utils.get_season_stats_from_sheet() with extra
#  columns that utils doesn't collect: Takeaways, Giveaways,
#  GWG, Interceptions. Tries multiple possible header names
#  since the sheet headers vary by setup.
# ════════════════════════════════════════════════════════════

def _get_extended_season_stats(config: dict) -> dict:
    """
    Calls utils.get_season_stats_from_sheet() then adds:
      TK  = Takeaways
      GV  = Giveaways
      GWG = Game Winning Goals
      INT = Interceptions
    Falls back gracefully if columns aren't found.
    """
    try:
        stats = utils.get_season_stats_from_sheet(config)
    except Exception as e:
        print(f"[{COG_NAME}] _get_extended_season_stats base call failed: {e}")
        return {}

    # Column name candidates (sheet headers vary)
    _TK_COLS  = ["Takeaways", "Takeaway", "sktakeaways", "TK", "Tk"]
    _GV_COLS  = ["Giveaways", "Giveaway", "skgiveaways", "GV", "Gv"]
    _GWG_COLS = ["GWGs", "GWG", "gwg", "skgwg", "Game Winning Goals", "Game-Winning Goals",
                 "GameWinningGoals", "Game Winning", "game winning", "GWGoals",
                 "Game Winner", "game winner", "Winners", "Winning Goals"]
    _INT_COLS = ["Interceptions", "Interception", "skinterceptions", "INT", "Int"]

    try:
        sh   = utils.get_sheet()
        if not sh:
            return stats
        ws   = sh.worksheet("Player Stats")
        rows = ws.get_all_values()
        h_idx, h = utils.find_header_row(rows, ["Username", "Team ID"])
        if h_idx == -1:
            return stats

        def _find_col(candidates):
            for c in candidates:
                if c in h:
                    return h.index(c)
            return -1

        c_name = h.index("Username")
        c_tk   = _find_col(_TK_COLS)
        c_gv   = _find_col(_GV_COLS)
        c_gwg  = _find_col(_GWG_COLS)
        c_int  = _find_col(_INT_COLS)

        print(f"[{COG_NAME}] Extended stats columns — "
              f"TK:{c_tk} GV:{c_gv} GWG:{c_gwg} INT:{c_int} "
              f"(headers: {h[:30]})")

        def _si(row, col):
            if col == -1 or col >= len(row): return 0
            try:    return int(float(row[col]))
            except: return 0

        for row in rows[h_idx + 1:]:
            if len(row) <= c_name: continue
            name = row[c_name].strip()
            if not name or name not in stats: continue
            s = stats[name]
            s.setdefault("TK",  0)
            s.setdefault("GV",  0)
            s.setdefault("GWG", 0)
            s.setdefault("INT", 0)
            s["TK"]  += _si(row, c_tk)
            s["GV"]  += _si(row, c_gv)
            s["GWG"] += _si(row, c_gwg)
            s["INT"] += _si(row, c_int)

    except Exception as e:
        print(f"[{COG_NAME}] _get_extended_season_stats enrichment error: {e}")

    return stats


# ════════════════════════════════════════════════════════════
#  LEADERBOARD IMAGE
# ════════════════════════════════════════════════════════════

def _generate_leaderboard_image(season_stats):
    # Enrich with extended stats (TK, GV, GWG, INT)
    # season_stats comes from utils — we need config to re-fetch
    # So we call our enricher and merge the extra keys in
    try:
        import json, os as _os
        cfg_path = _os.path.join(BASE_DIR, "config.json")
        with open(cfg_path) as f:
            _cfg = json.load(f)
        extended = _get_extended_season_stats(_cfg)
        # Merge extra keys into season_stats
        for name, s in season_stats.items():
            if name in extended:
                for k in ("TK", "GV", "GWG", "INT"):
                    s.setdefault(k, extended[name].get(k, 0))
    except Exception as e:
        print(f"[{COG_NAME}] leaderboard enrichment merge error: {e}")

    categories = [
        {"key": "P",             "name": "POINTS",        "pos": "Skater", "color": B["win"]},
        {"key": "G",             "name": "GOALS",         "pos": "Skater", "color": B["loss"]},
        {"key": "A",             "name": "ASSISTS",       "pos": "Skater", "color": B["accent"]},
        {"key": "Hits",          "name": "HITS",          "pos": "Skater", "color": B["dnf"]},
        {"key": "TK",            "name": "TAKEAWAYS",     "pos": "Skater", "color": B["gold"]},
        {"key": "GV",            "name": "GIVEAWAYS",     "pos": "Skater", "color": B["grey"]},
        {"key": "PIM",           "name": "PENALTIES",     "pos": "Skater", "color": B["loss"]},
        {"key": "INT",           "name": "INTERCEPTS",    "pos": "Skater", "color": B["accent2"]},
        {"key": "Save % Value",  "name": "SAVE %",        "pos": "Goalie", "color": B["gold"]},
        {"key": "Sv",            "name": "SAVES",         "pos": "Goalie", "color": B["silver"]},
    ]

    COLS    = 5
    COL_W   = 320
    START_Y = 140
    ROW_H   = 38
    PANEL_H = 14 + 52 + 4 + 10 * ROW_H + 10   # header + top pad + divider + rows + bottom
    WIDTH   = 30 + COLS * (COL_W + 10) + 30
    ROWS    = -(-len(categories) // COLS)       # ceiling
    HEIGHT  = START_Y + ROWS * (PANEL_H + 20) + 60

    img, draw = _base(WIDTH, HEIGHT)
    _draw_title_bar(draw, WIDTH, 120,
                    _league().upper() + " LEADERS",
                    subtitle="Season Statistics — Top Performers")

    for idx, cat in enumerate(categories):
        col = idx % COLS
        row = idx // COLS
        ox  = 30 + col * (COL_W + 10)
        oy  = START_Y + row * (PANEL_H + 20)

        draw = _fill_rect(draw, (ox, oy, ox + COL_W, oy + PANEL_H), BA["panel"])
        draw.rectangle((ox, oy, ox + COL_W, oy + 4),       fill=cat["color"])
        draw.text((ox + 12, oy + 10), cat["name"], font=FONTS["header"], fill=cat["color"])
        draw.rectangle((ox + 12, oy + 54, ox + COL_W - 12, oy + 56), fill=B["border"])

        players = [(n, s) for n, s in season_stats.items()
                   if s.get("Main Position") == cat["pos"]]
        if cat["name"] == "SAVE %":
            players = [(n, s) for n, s in players if s.get("GP", 0) >= 3]
        players.sort(key=lambda x: x[1].get(cat["key"], 0), reverse=True)

        rank_colors = [B["gold"], B["silver"], B["bronze"]]
        ly = oy + 66

        for rank_i, (pname, pstats) in enumerate(players[:10]):
            val   = pstats.get(cat["key"], 0)
            v_str = f"{val:.3f}" if "SAVE" in cat["name"] else str(int(val))
            rc    = rank_colors[rank_i] if rank_i < 3 else B["grey2"]
            pf    = B["white"] if rank_i < 3 else B["grey2"]

            if rank_i % 2 == 1:
                draw = _fill_rect(draw, (ox, ly, ox + COL_W, ly + ROW_H), BA["panel2"])

            draw.text((ox + 10, ly + 4), str(rank_i + 1) + ".", font=FONTS["small"], fill=rc)
            draw.text((ox + 36, ly + 4), _safe_str(pname[:16]),  font=FONTS["row"],   fill=pf)
            vw = draw.textlength(v_str, font=FONTS["row"])
            draw.text((ox + COL_W - 14 - vw, ly + 4), v_str,    font=FONTS["row"],   fill=rc)
            ly += ROW_H

    footer_y = START_Y + ROWS * (PANEL_H + 20) + 10
    footer_y = _draw_footer(draw, WIDTH, footer_y, _footer("Leaderboard"))
    img = img.crop((0, 0, WIDTH, footer_y))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  WIDE TEAM CARD
# ════════════════════════════════════════════════════════════

def _fetch_team_match_history(team_name: str) -> list:
    """
    Reads the Game Results sheet and returns all matches involving team_name.
    Returns list of dicts: {date, opponent, our_score, opp_score, result, game_type}
    Sorted most recent first. Returns [] on any failure.
    """
    try:
        sh = utils.get_sheet()
        if not sh:
            return []
        ws   = sh.worksheet("Game Results")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []

        header = [c.strip() for c in rows[0]]
        def col(n):
            try:    return header.index(n)
            except: return -1

        c_date  = col("Date")
        c_t1    = col("Team 1")
        c_s1    = col("Score")           # Team 1 score
        c_r1    = col("Result")          # Team 1 result
        c_t2    = col("Team 2")
        # Team 2 score and result are at c_s1+2 and c_r1+2 (same header names repeated)
        # Find second occurrence
        c_s2    = header.index("Score",  c_s1 + 1)  if "Score"  in header[c_s1+1:]  else c_s1 + 2
        c_r2    = header.index("Result", c_r1 + 1)  if "Result" in header[c_r1+1:]  else c_r1 + 2
        c_type  = col("Game Type")

        tname_lower = team_name.strip().lower()
        matches = []

        for row in rows[1:]:
            if not row or max(c_t1, c_t2) >= len(row):
                continue
            t1 = row[c_t1].strip()
            t2 = row[c_t2].strip()

            is_t1 = t1.lower() == tname_lower or tname_lower in t1.lower()
            is_t2 = t2.lower() == tname_lower or tname_lower in t2.lower()

            if not is_t1 and not is_t2:
                continue

            try:
                s1 = int(row[c_s1]) if c_s1 != -1 and c_s1 < len(row) else 0
                s2 = int(row[c_s2]) if c_s2 != -1 and c_s2 < len(row) else 0
            except (ValueError, TypeError):
                s1, s2 = 0, 0

            r1   = row[c_r1].strip()  if c_r1 != -1 and c_r1 < len(row) else ""
            r2   = row[c_r2].strip()  if c_r2 != -1 and c_r2 < len(row) else ""
            gtype = row[c_type].strip() if c_type != -1 and c_type < len(row) else ""
            date  = row[c_date].strip() if c_date != -1 and c_date < len(row) else ""

            if is_t1:
                matches.append({
                    "date":      date,
                    "opponent":  t2,
                    "our_score": s1,
                    "opp_score": s2,
                    "result":    r1,
                    "game_type": gtype,
                })
            else:
                matches.append({
                    "date":      date,
                    "opponent":  t1,
                    "our_score": s2,
                    "opp_score": s1,
                    "result":    r2,
                    "game_type": gtype,
                })

        # Most recent first
        matches.reverse()
        return matches

    except Exception as e:
        print(f"[{COG_NAME}] _fetch_team_match_history error: {e}")
        return []


def _generate_wide_team_card(team_name, roster_stats):
    # Fetch match history — blocking disk/sheet call but this runs in executor
    matches = _fetch_team_match_history(team_name)

    MATCH_ROW_H = 44
    LOGO_SIZE   = 36

    WIDTH  = 1900
    # Height: title(120) + table header(48) + roster rows + section gap +
    #         match header(56) + match col header(44) + match rows + footer(40)
    roster_h = 48 + len(roster_stats) * 46
    match_h  = (56 + 44 + len(matches) * MATCH_ROW_H) if matches else 0
    HEIGHT   = max(120 + roster_h + 30 + match_h + 60, 600)

    img, draw = _base(WIDTH, HEIGHT)
    _draw_title_bar(draw, WIDTH, 120,
                    f"{_safe_str(team_name).upper()} — TEAM CARD",
                    subtitle="Season Cumulative Statistics")

    logo = _get_logo(team_name, size=90)
    if logo:
        _paste_logo(img, logo, WIDTH - 110, 15)

    # ── ROSTER STATS TABLE ────────────────────────────────────
    y    = 128
    hdrs = ["Player","GP","G","A","PTS","+/-","Hits","S","PIM","Sv","GA","Sv%"]
    xs   = [40,380,470,560,650,760,870,990,1090,1230,1340,1440]
    y    = _draw_table_header(draw, xs, hdrs, y)

    for alt_i, (pname, s) in enumerate(
            sorted(roster_stats, key=lambda x: x[1].get("P", 0), reverse=True)):
        is_g = s.get("Main Position") == "Goalie"
        pm   = s.get("+/-", 0)
        pm_c = B["win"] if pm > 0 else (B["loss"] if pm < 0 else B["grey2"])
        sv, ga, svp = ("-", "-", "-")
        if is_g:
            sv_n = s.get("Sv", 0); ga_n = s.get("GA", 0); sa_n = sv_n + ga_n
            sv = str(sv_n); ga = str(ga_n)
            svp = f"{sv_n/sa_n:.3f}" if sa_n > 0 else "0.000"
        vals  = [_safe_str(pname[:20]), s.get("GP",0), s.get("G",0), s.get("A",0),
                 s.get("P",0), pm, s.get("Hits",0), s.get("S",0), s.get("PIM",0),
                 sv, ga, svp]
        fills = [B["accent"] if is_g else B["white"],
                 B["grey2"], B["grey2"], B["grey2"], B["win"], pm_c,
                 B["grey2"], B["grey2"], B["grey2"], B["grey2"], B["grey2"], B["grey2"]]
        y = _draw_table_row(draw, xs, vals, y, alt=alt_i % 2 == 1, fills=fills)

    y += 20

    # ── MATCH HISTORY ─────────────────────────────────────────
    if matches:
        y = _draw_section_header(draw, WIDTH, y, "MATCH HISTORY",
                                  color=B["accent"])

        # Summary pills — W / OTW / OTL / L / DNF counts
        w   = sum(1 for m in matches if m["result"] in ("W",  "W-FF"))
        otw = sum(1 for m in matches if m["result"] == "OTW")
        otl = sum(1 for m in matches if m["result"] == "OTL")
        l   = sum(1 for m in matches if m["result"] in ("L",  "L-FF"))
        gp  = len(matches)
        pts = w * 2 + otw * 2 + otl * 1

        pill_data = [
            ("GP",  str(gp),       B["grey2"]),
            ("W",   str(w + otw),  B["win"]),
            ("L",   str(l + otl),  B["loss"]),
            ("OTL", str(otl),      B["dnf"]),
            ("PTS", str(pts),      B["gold"]),
        ]
        px = 60
        for lbl, val, color in pill_data:
            lw = draw.textlength(lbl, font=FONTS["lbl"])
            vw = draw.textlength(val, font=FONTS["val"])
            bw = max(lw, vw) + 24
            draw = _fill_rect(draw, (px - bw//2, y, px + bw//2, y + 72), BA["panel"])
            draw.rectangle((px - bw//2, y, px + bw//2, y + 4), fill=color)
            draw.text((px - lw//2, y + 8), lbl, font=FONTS["lbl"], fill=B["grey"])
            draw.text((px - vw//2, y + 30), val, font=FONTS["val"], fill=B["white"])
            px += bw + 20
        y += 82

        # Match table columns:
        # LOGO | Opponent | Result | Score | Date | Type
        m_xs   = [14, 60, 480, 620, 750, 1000]
        m_hdrs = ["",  "Opponent", "Result", "Score", "Date", "Type"]
        y = _draw_table_header(draw, m_xs, m_hdrs, y, row_height=44)

        for alt_i, m in enumerate(matches):
            result = m["result"]
            if result in ("W", "W-FF", "OTW"):   rc = B["win"]
            elif result in ("L", "L-FF", "OTL"): rc = B["loss"]
            else:                                  rc = B["dnf"]

            score_str = f"{m['our_score']}  —  {m['opp_score']}"
            gt_label  = {"REG": "Regulation", "OT": "Overtime",
                         "DNF": "DNF"}.get(m["game_type"], m["game_type"])

            bg = BA["row_alt"] if alt_i % 2 == 1 else BA["row_main"]
            draw = _fill_rect(draw, (0, y, WIDTH, y + MATCH_ROW_H), bg)

            # Opponent logo
            opp_logo = _get_logo(m["opponent"], size=LOGO_SIZE)
            if opp_logo:
                _paste_logo(img, opp_logo,
                            m_xs[0], y + (MATCH_ROW_H - LOGO_SIZE) // 2)

            draw.text((m_xs[1], y + 7), _safe_str(m["opponent"][:28]),
                      font=FONTS["row"], fill=B["white"])
            draw.text((m_xs[2], y + 7), result,
                      font=FONTS["row"], fill=rc)
            draw.text((m_xs[3], y + 7), score_str,
                      font=FONTS["header"], fill=B["white"])
            draw.text((m_xs[4], y + 7), m["date"][:10],
                      font=FONTS["row"], fill=B["grey2"])
            draw.text((m_xs[5], y + 7), gt_label,
                      font=FONTS["row"], fill=B["grey"])

            y += MATCH_ROW_H

        y += 10

    y = _draw_footer(draw, WIDTH, y + 6,
                     _footer("Team Card"))
    img = img.crop((0, 0, WIDTH, y))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  GAME REPORT
# ════════════════════════════════════════════════════════════

def _generate_game_report(game_data):
    """
    Clean minimal game report.
    Layout: Hero score → Team stats comparison → Three Stars → Player tables
    """
    WIDTH = 1600
    try:
        c_ids  = list(game_data["clubs"].keys())
        c1_id, c2_id = c_ids[0], c_ids[1]
        c1, c2 = game_data["clubs"][c1_id], game_data["clubs"][c2_id]
        c1_name  = _safe_str(c1["details"]["name"][:24]).upper()
        c2_name  = _safe_str(c2["details"]["name"][:24]).upper()
        c1_raw   = c1["details"]["name"]
        c2_raw   = c2["details"]["name"]
        # Sum player goals — more accurate than clubs block for DNF games
        c1_score = sum(_safe_int(p.get("skgoals",0)) for p in game_data["players"].get(c1_id,{}).values())
        c2_score = sum(_safe_int(p.get("skgoals",0)) for p in game_data["players"].get(c2_id,{}).values())
    except Exception as e:
        print(f"[{COG_NAME}] game_report parse error: {e}")
        return io.BytesIO()

    def _totals(cid):
        t = {"S":0,"H":0,"TOA":0,"FOW":0,"FOL":0,"PIM":0,"G":0}
        for p in game_data["players"].get(cid,{}).values():
            t["S"]   += _safe_int(p.get("skshots",0))
            t["H"]   += _safe_int(p.get("skhits",0))
            t["TOA"] += _safe_int(p.get("skpossession",0))
            t["FOW"] += _safe_int(p.get("skfow",0))
            t["FOL"] += _safe_int(p.get("skfol",0))
            t["PIM"] += _safe_int(p.get("skpim",0))
            t["G"]   += _safe_int(p.get("skgoals",0))  # sum player goals — more accurate than clubs block
        return t

    def _count_player_rows():
        total = 0
        for cid in [c1_id, c2_id]:
            pl = list(game_data["players"].get(cid, {}).values())
            sk = [p for p in pl if p.get("position") != "goalie"]
            gl = [p for p in pl if p.get("position") == "goalie"]
            total += 48 + 44 + len(sk) * 44 + 16
            if gl: total += 48 + 44 + len(gl) * 44 + 16
        return total

    t1, t2 = _totals(c1_id), _totals(c2_id)
    t1_toa = f"{t1['TOA']//60}:{t1['TOA']%60:02d}"
    t2_toa = f"{t2['TOA']//60}:{t2['TOA']%60:02d}"

    # Determine winner for header coloring
    c1_won = c1_score > c2_score
    c1_col = B["win"]  if c1_won else B["grey2"]
    c2_col = B["win"]  if not c1_won else B["grey2"]

    HERO_H   = 200    # large score hero block
    STATS_H  = 310    # team stat comparison (now between tables)
    STARS_H  = 150    # three stars
    HEIGHT   = HERO_H + STARS_H + _count_player_rows() + STATS_H + 80
    HEIGHT   = max(HEIGHT, 800)

    img, draw = _base(WIDTH, HEIGHT)

    # ── HERO BLOCK ──────────────────────────────────────────────
    LOGO_H   = 90
    LOGO_PAD = 24
    NAME_H   = 28    # space reserved for name below logo
    HERO_H   = max(HERO_H, LOGO_H + NAME_H + 40)  # ensure names fit

    draw = _fill_rect(draw, (0, 0, WIDTH, HERO_H), BA["dark"])
    draw.rectangle((0, 0, 6, HERO_H), fill=c1_col)

    # Logos — vertically centred accounting for name below
    logo1  = _get_logo(c1_raw, size=LOGO_H)
    logo2  = _get_logo(c2_raw, size=LOGO_H)
    logo_y = (HERO_H - LOGO_H - NAME_H) // 2
    if logo1: _paste_logo(img, logo1, LOGO_PAD, logo_y)
    if logo2: _paste_logo(img, logo2, WIDTH - LOGO_PAD - LOGO_H, logo_y)

    # Team names — drawn INSIDE hero block, below logo with guaranteed clearance
    name_y      = logo_y + LOGO_H + 4
    NAME_AREA_W = (WIDTH // 2) - LOGO_PAD - 10
    for name, x_start, align, col in [
        (c1_name, LOGO_PAD,                  "left",  c1_col),
        (c2_name, WIDTH - LOGO_PAD - LOGO_H, "right", c2_col),
    ]:
        display = name
        while draw.textlength(display, font=FONTS["small"]) > NAME_AREA_W and len(display) > 4:
            display = display[:-1]
        if display != name:
            display = display.rstrip()[:-1] + ".."
        nw = draw.textlength(display, font=FONTS["small"])
        tx = x_start if align == "left" else x_start + LOGO_H - nw
        # Clamp so text never goes past the gold bottom rule
        safe_y = min(name_y, HERO_H - 26)
        draw.text((tx, safe_y), display, font=FONTS["small"], fill=col)

    # Score — centred
    score_str = f"{c1_score}  —  {c2_score}"
    sw        = draw.textlength(score_str, font=FONTS["score"])
    score_y   = (HERO_H - 100) // 2 - 8
    draw.text(((WIDTH - sw) // 2, score_y), score_str, font=FONTS["score"], fill=B["white"])

    # Gold bottom rule — drawn LAST so nothing paints over it
    draw.rectangle((0, HERO_H - 2, WIDTH, HERO_H), fill=B["accent"])

    # ── THREE STARS ─────────────────────────────────────────────
    ty = HERO_H + 10

    all_p = [p for cid in [c1_id, c2_id]
             for p in game_data["players"].get(cid, {}).values()]
    all_p.sort(
        key=lambda p: (
            _safe_int(p.get("glsaves",0)) * 0.5 - _safe_int(p.get("glga",0)) + 10
            if p.get("position") == "goalie"
            else _safe_int(p.get("skgoals",0)) * 3 + _safe_int(p.get("skassists",0)) * 2
        ),
        reverse=True
    )

    stars_lbl = "THREE STARS OF THE GAME"
    slw = draw.textlength(stars_lbl, font=FONTS["h3"])
    draw.text(((WIDTH - slw) // 2, ty), stars_lbl, font=FONTS["h3"], fill=B["grey"])
    ty += 44

    ranks   = ["1ST *", "2ND *", "3RD *"]
    sc      = [B["gold"], B["silver"], B["bronze"]]
    star_xs = [WIDTH // 6, WIDTH // 2, 5 * WIDTH // 6]

    for i, p in enumerate(all_p[:3]):
        pn   = _safe_str(p.get("playername", "")[:18])
        is_g = p.get("position") == "goalie"
        st   = (f"{_safe_int(p.get('glsaves',0))} SV"
                if is_g else
                f"{_safe_int(p.get('skgoals',0))}G  {_safe_int(p.get('skassists',0))}A")
        sx   = star_xs[i]
        rw   = draw.textlength(ranks[i], font=FONTS["badge"])
        pw   = draw.textlength(pn,       font=FONTS["row"])
        stw  = draw.textlength(st,       font=FONTS["small"])
        draw.text((sx - rw  // 2, ty),      ranks[i], font=FONTS["badge"], fill=sc[i])
        draw.text((sx - pw  // 2, ty + 34), pn,       font=FONTS["row"],   fill=B["white"])
        draw.text((sx - stw // 2, ty + 70), st,       font=FONTS["small"], fill=sc[i])

    ty += STARS_H - 20

    # helper — draws one team's skater + goalie tables
    def _draw_team_tables(cid, ty):
        cname = _safe_str(game_data["clubs"][cid]["details"]["name"]).upper()
        craw  = game_data["clubs"][cid]["details"]["name"]
        col   = B["accent"] if cid == c1_id else B["grey2"]
        pl    = list(game_data["players"].get(cid, {}).values())
        sk    = sorted(
            [p for p in pl if p.get("position") != "goalie"],
            key=lambda p: _safe_int(p.get("skgoals",0))*3 + _safe_int(p.get("skassists",0))*2,
            reverse=True
        )
        gl = [p for p in pl if p.get("position") == "goalie"]

        ty = _draw_section_header(draw, WIDTH, ty,
                                f"{cname} — SKATERS", color=col)
        sk_xs = [40, 400, 540, 640, 740, 870, 1000, 1130, 1260]
        ty = _draw_table_header(draw, sk_xs,
                                ["Player","Pos","G","A","PTS","+/-","Shots","Hits","PIM"],
                                ty, row_height=44, font=FONTS["small"])
        for alt_i, p in enumerate(sk):
            pm   = _safe_int(p.get("skplusmin", p.get("plus_minus", 0)))
            pm_c = B["win"] if pm > 0 else (B["loss"] if pm < 0 else B["grey2"])
            vals = [
                _safe_str(p.get("playername","")[:22]),
                _shorten_pos(p.get("position","")),
                _safe_int(p.get("skgoals",0)),
                _safe_int(p.get("skassists",0)),
                _safe_int(p.get("skgoals",0)) + _safe_int(p.get("skassists",0)),
                pm,
                _safe_int(p.get("skshots",0)),
                _safe_int(p.get("skhits",0)),
                _safe_int(p.get("skpim",0)),
            ]
            ty = _draw_table_row(draw, sk_xs, vals, ty, row_height=44, alt=alt_i%2==1,
                                 fills=[B["white"],B["grey"],B["grey2"],B["grey2"],
                                        B["win"],pm_c,B["grey2"],B["grey2"],B["grey2"]])
        if gl:
            ty += 8
            ty = _draw_section_header(draw, WIDTH, ty,
                                    f"{cname} — GOALIES", color=col)
            gl_xs = [40, 400, 560, 680, 800, 980]
            ty = _draw_table_header(draw, gl_xs,
                                    ["Player","SA","SV","GA","SV%","TOI"],
                                    ty, row_height=44, font=FONTS["small"])
            for alt_i, p in enumerate(gl):
                sv2   = _safe_int(p.get("glsaves",0))
                ga2   = _safe_int(p.get("glga",0))
                sa2   = sv2 + ga2
                svp   = f"{sv2/sa2:.3f}" if sa2 > 0 else "0.000"
                toi   = _safe_int(p.get("toiseconds",0))
                toi_s = f"{toi//60}:{toi%60:02d}"
                ty = _draw_table_row(draw, gl_xs,
                                     [_safe_str(p.get("playername","")[:22]),
                                      sa2, sv2, ga2, svp, toi_s],
                                     ty, row_height=44, alt=alt_i%2==1,
                                     fills=[B["white"],B["grey2"],B["win"],B["loss"],
                                            B["gold"],B["grey2"]])
        return ty + 16

    # ── TEAM 1 PLAYERS ──────────────────────────────────────────
    ty = _draw_team_tables(c1_id, ty)

    # ── TEAM STATS — centred divider between teams, logos on sides ─
    ty += 4
    draw.rectangle((0, ty, WIDTH, ty + 2), fill=B["border"])
    ty += 10

    stat_rows = [
        ("SHOTS",          t1["S"],   t2["S"]),
        ("HITS",           t1["H"],   t2["H"]),
        ("TIME ON ATTACK", t1_toa,    t2_toa),
        ("FACEOFF WINS",   t1["FOW"], t2["FOW"]),
        ("PENALTY MINS",   t1["PIM"], t2["PIM"]),
    ]

    ROW_H2 = 50
    BAR_W  = 260
    BAR_X  = WIDTH // 2 - BAR_W // 2

    # Section label
    lbl = "TEAM STATS"
    lw  = draw.textlength(lbl, font=FONTS["h3"])
    draw.text(((WIDTH - lw) // 2, ty), lbl, font=FONTS["h3"], fill=B["grey"])
    ty += 36

    for label, v1, v2 in stat_rows:
        draw = _fill_rect(draw, (0, ty, WIDTH, ty + ROW_H2), BA["panel"])
        draw.rectangle((0, ty + ROW_H2 - 1, WIDTH, ty + ROW_H2), fill=B["border"])
        label_w = draw.textlength(label, font=FONTS["small"])
        draw.text(((WIDTH - label_w) // 2, ty + 5), label, font=FONTS["small"], fill=B["grey"])
        v1s = str(v1); v2s = str(v2)
        v1w = draw.textlength(v1s, font=FONTS["header"])
        draw.text((BAR_X - 20 - v1w, ty + 7), v1s, font=FONTS["header"], fill=B["accent"])
        draw.text((BAR_X + BAR_W + 20, ty + 7), v2s, font=FONTS["header"], fill=B["grey2"])
        try:
            n1 = float(str(v1).replace(":", "").replace(".", ""))
            n2 = float(str(v2).replace(":", "").replace(".", ""))
            total = n1 + n2
            if total > 0:
                draw.rectangle((BAR_X, ty + 36, BAR_X + BAR_W, ty + 44), fill=B["border"])
                pct = int(BAR_W * n1 / total)
                draw.rectangle((BAR_X, ty + 36, BAR_X + pct, ty + 44), fill=B["accent"])
        except: pass
        ty += ROW_H2

    ty += 10
    draw.rectangle((0, ty, WIDTH, ty + 2), fill=B["border"])
    ty += 8

    # ── TEAM 2 PLAYERS ──────────────────────────────────────────
    ty = _draw_team_tables(c2_id, ty)

    ty = _draw_footer(draw, WIDTH, ty + 4, _footer("Game Report"))
    img = img.crop((0, 0, WIDTH, ty))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  STANDINGS
# ════════════════════════════════════════════════════════════

def _generate_standings_image(rows):
    if not rows:
        buf=io.BytesIO(); Image.new("RGB",(400,100),B["bg"]).save(buf,"PNG"); buf.seek(0); return buf

    LOGO_SIZE=36; WIDTH=1700; ROW_H=56; HDR_H=120; COL_H=50
    HEIGHT=HDR_H+COL_H+len(rows)*ROW_H+60
    img,draw=_base(WIDTH,HEIGHT)
    _draw_title_bar(draw,WIDTH,HDR_H,_league().upper() + " STANDINGS",subtitle=f"{len(rows)} Teams")
    xs  =[30,90,160,700,810,920,1030,1140,1280,1400,1520]
    hdrs=["#","","Team","GP","W","L","OTL","PTS","GF","GA","+/-"]
    y=HDR_H; y=_draw_table_header(draw,xs,hdrs,y,row_height=COL_H)

    for alt_i,row in enumerate(rows):
        try:
            if isinstance(row,dict):
                rank=alt_i+1; tname=row.get("team_name",row.get("name","Unknown"))
                gp=row.get("GP",0); w=row.get("W",0); l=row.get("L",0)
                otl=row.get("OTL",row.get("OTW",0)); pts=row.get("PTS",0)
                gf=row.get("GF",0); ga=row.get("GA",0); diff=row.get("diff",gf-ga)
            else:
                rank,tname,gp,w,l,otl,pts,gf,ga=row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8]
                diff=row[9] if len(row)>9 else (_safe_int(gf)-_safe_int(ga))

            diff_str=f"+{diff}" if _safe_int(diff)>0 else str(diff)
            pts_c=B["gold"] if alt_i==0 else (B["win"] if alt_i<4 else B["grey2"])
            diff_c=B["win"] if _safe_int(diff)>0 else (B["loss"] if _safe_int(diff)<0 else B["grey2"])
            vals=[str(rank),"",_safe_str(str(tname)[:26]),str(gp),str(w),str(l),str(otl),str(pts),str(gf),str(ga),diff_str]
            fills=[B["grey"],B["white"],B["white"],B["grey2"],B["grey2"],B["grey2"],B["grey2"],pts_c,B["grey2"],B["grey2"],diff_c]
            draw = _fill_rect(draw, (0,y,WIDTH,y+ROW_H), BA["row_alt"] if alt_i%2==1 else BA["row_main"])
            for i,(v,f) in enumerate(zip(vals,fills)):
                if i==1: continue
                draw.text((xs[i],y+14),str(v),font=FONTS["row"],fill=f)
            logo=_get_logo(str(tname),size=LOGO_SIZE)
            if logo: _paste_logo(img,logo,xs[1],y+(ROW_H-LOGO_SIZE)//2)
        except Exception as e:
            print(f"[{COG_NAME}] standings row {alt_i} error: {e}")
        y+=ROW_H
        draw.rectangle((0,y,WIDTH,y+1),fill=B["border"])

    y=_draw_footer(draw,WIDTH,y+6,_footer("Standings"))
    img=img.crop((0,0,WIDTH,y)); buf=io.BytesIO(); img.save(buf,"PNG"); buf.seek(0)
    return buf


def _generate_season_standings_image(standings_data, team_names=None):
    if not standings_data:
        buf=io.BytesIO(); Image.new("RGB",(400,100),B["bg"]).save(buf,"PNG"); buf.seek(0); return buf
    rows=[]
    for i,row in enumerate(standings_data):
        tname=row.get("team_name") or (team_names or {}).get(row.get("team_id",""),"Unknown")
        rows.append([i+1,tname,row.get("GP",0),row.get("W",0),row.get("L",0),
                     row.get("OTL",row.get("OTW",0)),row.get("PTS",0),
                     row.get("GF",0),row.get("GA",0),row.get("GF",0)-row.get("GA",0)])
    return _generate_standings_image(rows)


# ════════════════════════════════════════════════════════════
#  SEASON SUMMARY IMAGE  (patches results.py via utils)
#  Returns a LIST of io.BytesIO buffers — one per page.
#  Layout: two columns of games side by side, ~20 rows per col
#  = ~40 games per page. Bigger logos + larger score text.
# ════════════════════════════════════════════════════════════

def _generate_season_summary_image(summary: list, team_names: dict) -> list:
    """
    Two-column game cards. Each card:
      Header row: #N left | FINAL/DNF/OT right
      Team 1 row: logo + name | score (right-aligned, green/red)
      Team 2 row: logo + name | score (right-aligned, red/green)
    Games grouped by date with a date separator bar.
    """
    GAMES_PER_PAGE = 30
    CARD_W         = 560
    CARD_HDR_H     = 30    # "#1  FINAL" header
    TEAM_ROW_H     = 52    # each team row height
    CARD_H         = CARD_HDR_H + TEAM_ROW_H * 2
    CARD_GAP_X     = 12
    CARD_GAP_Y     = 8
    LOGO_SIZE      = 36
    DATE_HDR_H     = 34
    HDR_H          = 130
    COL_HDR_H      = 46
    COLS           = 2
    WIDTH          = COLS * CARD_W + (COLS + 1) * CARD_GAP_X  # ~1144

    def _result_color(r):
        if r in ("W", "OTW", "W-FF", "Mercy W"):  return B["win"]
        if r in ("L", "OTL", "L-FF", "Mercy L"):  return B["loss"]
        return B["dnf"]

    def _score_colors(r1):
        won  = r1 in ("W", "OTW", "W-FF", "Mercy W")
        lost = r1 in ("L", "OTL", "L-FF", "Mercy L")
        if won:   return B["win"],  B["loss"]
        if lost:  return B["loss"], B["win"]
        return B["dnf"], B["dnf"]

    def _type_label(gt, r1):
        if "FF" in r1: return "DNF"
        if gt == "OT": return "OT"
        return "FINAL"

    def _type_color(lbl):
        if lbl == "DNF": return B["dnf"]
        if lbl == "OT":  return B["accent"]
        return B["grey2"]

    sorted_summary = sorted(summary, key=lambda g: (g["date"], g["match_id"]))
    reg_total = sum(1 for g in summary if g["game_type"] == "REG")
    ot_total  = sum(1 for g in summary if g["game_type"] == "OT")
    dnf_total = sum(1 for g in summary if g["game_type"] == "DNF")

    chunks      = [sorted_summary[i:i+GAMES_PER_PAGE]
                   for i in range(0, max(1, len(sorted_summary)), GAMES_PER_PAGE)]
    total_pages = len(chunks)
    pages       = []

    for page_idx, games in enumerate(chunks):
        is_current = (page_idx == total_pages - 1)
        start_num  = page_idx * GAMES_PER_PAGE + 1
        end_num    = start_num + len(games) - 1
        lbl        = f"Games {start_num}\u2013{end_num}"

        from collections import OrderedDict
        date_groups = OrderedDict()
        for g in games:
            date_groups.setdefault(g["date"][:10], []).append(g)

        # Height: title + col_hdr + per date: date_hdr + rows_of_cards*(CARD_H+gap)
        total_card_rows = sum(-(-len(gs) // COLS) for gs in date_groups.values())
        TITLE_BAR_H = 150
        HEIGHT = (TITLE_BAR_H + COL_HDR_H
                  + len(date_groups) * (DATE_HDR_H + CARD_GAP_Y)
                  + total_card_rows * (CARD_H + CARD_GAP_Y)
                  + 60)

        img, draw = _base(WIDTH, HEIGHT)

        # Title bar — league label + title + meta with breathing room
        TITLE_BAR_H = 150
        draw = _fill_rect(draw, (0, 0, WIDTH, TITLE_BAR_H), BA["dark"])
        draw.rectangle((0, 0, 6, TITLE_BAR_H), fill=B["accent"])
        draw.text((28, 10), _league().upper(), font=FONTS["small"], fill=B["accent"])
        draw.text((28, 34), "SEASON RESULTS", font=FONTS["title"], fill=B["white"])
        meta = (f"{len(summary)} Games  \u2022  {reg_total} Reg  \u2022  "
                f"{ot_total} OT  \u2022  {dnf_total} DNF  \u2022  {lbl}"
                + ("  \u2022  CURRENT WEEK" if is_current else ""))
        draw.text((30, TITLE_BAR_H - 28), meta, font=FONTS["small"], fill=B["grey"])
        draw.rectangle((0, TITLE_BAR_H - 2, WIDTH, TITLE_BAR_H), fill=B["accent"])

        # Col header
        y = TITLE_BAR_H
        draw = _fill_rect(draw, (0, y, WIDTH, y + COL_HDR_H), BA["panel2"])
        draw.rectangle((0, y + COL_HDR_H - 1, WIDTH, y + COL_HDR_H), fill=B["accent"])
        gw = draw.textlength("GAME RESULTS", font=FONTS["small"])
        draw.text(((WIDTH - gw) // 2, y + 12), "GAME RESULTS",
                  font=FONTS["small"], fill=B["accent"])
        y += COL_HDR_H

        game_num = start_num

        for date_str, date_games in date_groups.items():
            # Date separator
            draw = _fill_rect(draw, (0, y, WIDTH, y + DATE_HDR_H), BA["panel2"])
            draw.rectangle((0, y, 4, y + DATE_HDR_H), fill=B["accent2"])
            try:
                from datetime import datetime as _dt
                dlabel = _dt.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d %Y").upper()
            except Exception:
                dlabel = date_str
            dw = draw.textlength(dlabel, font=FONTS["small"])
            draw.text(((WIDTH - dw) // 2, y + 9), dlabel,
                      font=FONTS["small"], fill=B["accent"])
            y += DATE_HDR_H + CARD_GAP_Y

            for row_start in range(0, len(date_games), COLS):
                row_games = date_games[row_start:row_start + COLS]

                for col_i, g in enumerate(row_games):
                    cx = CARD_GAP_X + col_i * (CARD_W + CARD_GAP_X)
                    cy = y
                    cw = CARD_W

                    t1_raw = team_names.get(g["team1_id"], g["team1_id"])
                    t2_raw = team_names.get(g["team2_id"], g["team2_id"])
                    r1c    = _result_color(g["result_t1"])
                    r2c    = _result_color(g["result_t2"])
                    sc1, sc2 = _score_colors(g["result_t1"])
                    tlbl   = _type_label(g["game_type"], g["result_t1"])
                    tc     = _type_color(tlbl)

                    # Card background
                    draw = _fill_rect(draw, (cx, cy, cx + cw, cy + CARD_H), BA["panel"])

                    # Card header bar — no color bar, just dark
                    draw = _fill_rect(draw, (cx, cy, cx + cw, cy + CARD_HDR_H), BA["dark"])
                    draw.text((cx + 10, cy + 7), f"#{game_num}",
                              font=FONTS["small"], fill=B["grey"])
                    tlbl_w = draw.textlength(tlbl, font=FONTS["small"])
                    draw.text((cx + cw - tlbl_w - 10, cy + 7), tlbl,
                              font=FONTS["small"], fill=tc)

                    # Team 1 row
                    t1y = cy + CARD_HDR_H
                    draw = _fill_rect(draw, (cx, t1y, cx + cw, t1y + TEAM_ROW_H), BA["panel"])
                    logo1 = _get_logo(t1_raw, size=LOGO_SIZE)
                    logo_pad_y = (TEAM_ROW_H - LOGO_SIZE) // 2
                    if logo1:
                        _paste_logo(img, logo1, cx + 8, t1y + logo_pad_y)
                    draw.text((cx + 8 + LOGO_SIZE + 6, t1y + (TEAM_ROW_H - 30) // 2),
                              _safe_str(t1_raw[:22]), font=FONTS["row"], fill=B["white"])
                    s1w = draw.textlength(str(g["score_t1"]), font=FONTS["h2"])
                    draw.text((cx + cw - s1w - 12, t1y + (TEAM_ROW_H - 48) // 2),
                              str(g["score_t1"]), font=FONTS["h2"], fill=sc1)

                    # Divider between teams
                    draw.rectangle((cx + 8, t1y + TEAM_ROW_H - 1,
                                    cx + cw - 8, t1y + TEAM_ROW_H), fill=B["border"])

                    # Team 2 row
                    t2y = t1y + TEAM_ROW_H
                    draw = _fill_rect(draw, (cx, t2y, cx + cw, t2y + TEAM_ROW_H), BA["panel2"])
                    logo2 = _get_logo(t2_raw, size=LOGO_SIZE)
                    if logo2:
                        _paste_logo(img, logo2, cx + 8, t2y + logo_pad_y)
                    draw.text((cx + 8 + LOGO_SIZE + 6, t2y + (TEAM_ROW_H - 30) // 2),
                              _safe_str(t2_raw[:22]), font=FONTS["row"], fill=B["white"])
                    s2w = draw.textlength(str(g["score_t2"]), font=FONTS["h2"])
                    draw.text((cx + cw - s2w - 12, t2y + (TEAM_ROW_H - 48) // 2),
                              str(g["score_t2"]), font=FONTS["h2"], fill=sc2)

                    game_num += 1

                y += CARD_H + CARD_GAP_Y

            y += 4

        _draw_footer(draw, WIDTH, y + 6, _footer("Season Results"))
        img = img.crop((0, 0, WIDTH, y + 46))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        pages.append((buf, lbl, is_current))

    return pages


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class ImageEngine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        patches = {
            "generate_player_card":            _generate_player_card,
            "generate_roster_image":           _generate_roster_image,
            # generate_leaderboard_image patched by leaderboard_engine.py instead
            "generate_wide_team_card":         _generate_wide_team_card,
            "generate_game_report":            _generate_game_report,
            "generate_standings_image":        _generate_standings_image,
            "generate_season_standings_image": _generate_season_standings_image,
            "generate_season_summary_image":   _generate_season_summary_image,
        }
        for name, fn in patches.items():
            try:
                setattr(utils, name, fn)
                print(f"  ✔ [{COG_NAME}] patched {name}")
            except Exception as e:
                print(f"  ✘ [{COG_NAME}] failed to patch {name}: {e}")
        print(f"✅ [{COG_NAME}] v{VERSION} — All patches applied")

    async def cog_load(self):
        await utils.send_log(self.bot,
            f"🎨 **ImageEngine v{VERSION}** loaded — Roster 2-up layout + positional GP active")


async def setup(bot):
    await bot.add_cog(ImageEngine(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
