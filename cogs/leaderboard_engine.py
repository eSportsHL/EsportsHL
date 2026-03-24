# ============================================================
#  Echelon League Bot — leaderboard_engine.py
#  Version: 1.0.0
#  NEW COG — Never modifies utils.py, image_engine.py, or any
#  existing cog. Patches only generate_leaderboard_image.
#
#  Changes vs image_engine.py leaderboard:
#    - Each row now shows: rank, team logo, player name (X GP), value
#    - Added categories: Interceptions, Blocked Shots, Desp. Saves
#    - 5-column layout, wider panels to fit logo + GP
#    - Logo loaded from ~/Desktop/echel/logos/ via team_logos.py
#      (same source as standings/roster images)
#    - Team name read from season_stats["Team"] (added by statsreader)
#
#  Load order: must load AFTER image_engine.py and statsreader.py
#
#  Changelog:
#    v1.0.0 — Initial release.
# ============================================================

VERSION  = "1.1.0"
COG_NAME = "LeaderboardEngine"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Leaderboard with logos + GP")

import io
import os
import utils
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(utils.__file__))

# ════════════════════════════════════════════════════════════
#  BRAND — matches image_engine.py exactly
# ════════════════════════════════════════════════════════════

B = {
    "bg":         "#0a0c0f",
    "panel":      "#12161c",
    "panel2":     "#181d25",
    "dark":       "#060709",
    "border":     "#252b35",
    "header_row": "#181d25",
    "row_main":   "#0a0c0f",
    "row_alt":    "#10141a",
    "accent":     "#C9A84C",
    "accent2":    "#8B6914",
    "win":        "#4ade80",
    "loss":       "#f87171",
    "dnf":        "#fb923c",
    "gold":       "#C9A84C",
    "silver":     "#9ca3af",
    "bronze":     "#b07040",
    "white":      "#f0f2f5",
    "grey":       "#6b7280",
    "grey2":      "#9ca3af",
}


def _font(size):
    try:
        return ImageFont.truetype(os.path.join(BASE_DIR, "font.ttf"), size)
    except:
        return ImageFont.load_default()


FONTS = {
    "title":  _font(68),
    "h2":     _font(48),
    "header": _font(38),
    "row":    _font(30),
    "small":  _font(22),
    "badge":  _font(26),
    "lbl":    _font(24),
}


def _safe_str(s):
    if not isinstance(s, str):
        s = str(s)
    return s.encode("ascii", errors="ignore").decode("ascii").strip()


def _safe_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _league():
    try:    return utils.get_league_name()
    except: return utils.load_config().get("league_name", "League")


def _botname():
    try:    return utils.get_bot_name()
    except: return utils.load_config().get("bot_name", "Stats Bot")


def _footer_text():
    return f"{_botname()}  •  Leaderboard  •  Leaderboard Engine v{VERSION}"


# ════════════════════════════════════════════════════════════
#  LOGO HELPER — delegates to team_logos.py same as image_engine
# ════════════════════════════════════════════════════════════

def _get_logo(team_name: str, size: int = 32):
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
#  CANVAS HELPERS
# ════════════════════════════════════════════════════════════

def _base(width, height):
    try:
        bg = Image.open(os.path.join(BASE_DIR, "background.png")).resize((width, height)).convert("RGBA")
        overlay = Image.new("RGBA", bg.size, (6, 7, 9, 210))
        img = Image.alpha_composite(bg, overlay).convert("RGB")
        return img, ImageDraw.Draw(img)
    except:
        pass
    img  = Image.new("RGB", (width, height), color=B["bg"])
    draw = ImageDraw.Draw(img)
    for i in range(0, height, 2):
        alpha = int(6 * (1 - i / height))
        c = (10 + alpha, 14 + alpha, 20 + alpha)
        draw.line([(0, i), (width, i)], fill=c)
    return img, ImageDraw.Draw(img)


def _draw_title_bar(draw, width, height, title, subtitle=""):
    draw.rectangle((0, 0, width, height), fill=B["dark"])
    draw.rectangle((0, 0, 6, height), fill=B["accent"])
    draw.text((28, 14), title, font=FONTS["title"], fill=B["white"])
    if subtitle:
        draw.text((32, 88), subtitle, font=FONTS["small"], fill=B["grey"])
    draw.rectangle((0, height - 2, width, height), fill=B["accent"])


def _draw_footer(draw, width, y, text):
    draw.rectangle((0, y, width, y + 1), fill=B["accent2"])
    draw.rectangle((0, y + 1, width, y + 38), fill=B["dark"])
    fw = draw.textlength(text, font=FONTS["small"])
    draw.text(((width - fw) / 2, y + 10), text, font=FONTS["small"], fill=B["grey"])
    return y + 38


# ════════════════════════════════════════════════════════════
#  LEADERBOARD CATEGORIES
# ════════════════════════════════════════════════════════════

CATEGORIES = [
    # Skaters
    {"key": "P",    "name": "POINTS",        "pos": "Skater", "color": B["win"],    "fmt": "int"},
    {"key": "G",    "name": "GOALS",         "pos": "Skater", "color": B["loss"],   "fmt": "int"},
    {"key": "A",    "name": "ASSISTS",       "pos": "Skater", "color": B["accent"], "fmt": "int"},
    {"key": "Hits", "name": "HITS",          "pos": "Skater", "color": B["dnf"],    "fmt": "int"},
    {"key": "INT",  "name": "INTERCEPTS",    "pos": "Skater", "color": B["accent2"],"fmt": "int"},
    {"key": "BS",   "name": "BLOCKS",        "pos": "Skater", "color": B["silver"], "fmt": "int"},
    {"key": "TK",   "name": "TAKEAWAYS",     "pos": "Skater", "color": B["gold"],   "fmt": "int"},
    {"key": "GV",   "name": "GIVEAWAYS",     "pos": "Skater", "color": B["grey"],   "fmt": "int"},
    {"key": "PIM",  "name": "PENALTIES",     "pos": "Skater", "color": B["loss"],   "fmt": "int"},
    # Goalies
    {"key": "Save % Value", "name": "SAVE %",      "pos": "Goalie", "color": B["gold"],   "fmt": "pct"},
    {"key": "Sv",           "name": "SAVES",        "pos": "Goalie", "color": B["silver"], "fmt": "int"},
    {"key": "DS",           "name": "DESP SAVES",   "pos": "Goalie", "color": B["win"],    "fmt": "int"},
]


# ════════════════════════════════════════════════════════════
#  PATCHED LEADERBOARD GENERATOR
# ════════════════════════════════════════════════════════════

LOGO_SIZE = 32   # px — fits comfortably in a 42px row
COLS      = 4
COL_W     = 390  # wider than original 320 to fit logo + GP text
START_Y   = 140
ROW_H     = 42
TOP_PAD   = 16
HDR_H     = 52
DIVIDER_H = 2
PANEL_H   = TOP_PAD + HDR_H + DIVIDER_H + 10 * ROW_H + 10


def _generate_leaderboard_image(season_stats):
    ROWS   = -(-len(CATEGORIES) // COLS)
    WIDTH  = 30 + COLS * (COL_W + 10) + 30
    HEIGHT = START_Y + ROWS * (PANEL_H + 20) + 60

    img, draw = _base(WIDTH, HEIGHT)
    _draw_title_bar(
        draw, WIDTH, 120,
        _league().upper() + " LEADERS",
        subtitle="Season Statistics — Top Performers"
    )

    rank_colors = [B["gold"], B["silver"], B["bronze"]]

    for idx, cat in enumerate(CATEGORIES):
        col = idx % COLS
        row = idx // COLS
        ox  = 30 + col * (COL_W + 10)
        oy  = START_Y + row * (PANEL_H + 20)

        # Panel background
        draw.rectangle((ox, oy, ox + COL_W, oy + PANEL_H), fill=B["panel"])
        draw.rectangle((ox, oy, ox + COL_W, oy + 4),        fill=cat["color"])

        # Category header
        draw.text((ox + 12, oy + 10), cat["name"], font=FONTS["header"], fill=cat["color"])
        draw.rectangle(
            (ox + 12, oy + TOP_PAD + HDR_H - 2, ox + COL_W - 12, oy + TOP_PAD + HDR_H),
            fill=B["border"]
        )

        # Filter and sort players
        players = [
            (n, s) for n, s in season_stats.items()
            if s.get("Main Position") == cat["pos"]
        ]
        if cat["name"] == "SAVE %":
            players = [(n, s) for n, s in players if s.get("GP", 0) >= 3]
        players.sort(key=lambda x: x[1].get(cat["key"], 0), reverse=True)

        ly = oy + TOP_PAD + HDR_H + DIVIDER_H

        for rank_i, (pname, pstats) in enumerate(players[:10]):
            val   = pstats.get(cat["key"], 0)
            gp    = pstats.get("GP", 0)
            team  = pstats.get("Team", "")
            v_str = f"{val:.3f}" if cat["fmt"] == "pct" else str(_safe_int(val))
            rc    = rank_colors[rank_i] if rank_i < 3 else B["grey2"]
            pf    = B["white"] if rank_i < 3 else B["grey2"]
            gp_f  = B["grey"]

            # Alternating row background
            if rank_i % 2 == 1:
                draw.rectangle(
                    (ox, ly, ox + COL_W, ly + ROW_H),
                    fill=B["panel2"]
                )

            row_cy = ly + (ROW_H - LOGO_SIZE) // 2

            # Rank number
            draw.text(
                (ox + 8, ly + (ROW_H - 22) // 2),
                str(rank_i + 1) + ".",
                font=FONTS["small"], fill=rc
            )

            # Team logo
            logo = _get_logo(team, size=LOGO_SIZE)
            if logo:
                _paste_logo(img, logo, ox + 34, row_cy)
            else:
                # Fallback: coloured dot
                draw.ellipse(
                    (ox + 34, row_cy + 8, ox + 34 + 16, row_cy + 24),
                    fill=rc
                )

            # Player name + GP in brackets
            name_x  = ox + 34 + LOGO_SIZE + 6
            gp_tag  = f" ({gp} GP)"
            name_str = _safe_str(pname[:14])
            full_str = name_str + gp_tag
            # Draw name in white/grey, GP tag in grey
            nw = draw.textlength(name_str, font=FONTS["row"])
            draw.text(
                (name_x, ly + (ROW_H - 30) // 2),
                name_str,
                font=FONTS["row"], fill=pf
            )
            draw.text(
                (name_x + nw, ly + (ROW_H - 22) // 2 + 2),
                gp_tag,
                font=FONTS["small"], fill=gp_f
            )

            # Stat value — right-aligned
            vw = draw.textlength(v_str, font=FONTS["header"])
            draw.text(
                (ox + COL_W - 12 - vw, ly + (ROW_H - 38) // 2),
                v_str,
                font=FONTS["header"], fill=rc
            )

            ly += ROW_H

    footer_y = START_Y + ROWS * (PANEL_H + 20) + 10
    footer_y = _draw_footer(draw, WIDTH, footer_y, _footer_text())
    img = img.crop((0, 0, WIDTH, footer_y))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class LeaderboardEngine(commands.Cog):
    """
    Patches utils.generate_leaderboard_image with an upgraded
    version that shows team logo, GP, and extra stat categories.
    Must load after image_engine.py so it wins the patch race.
    """

    def __init__(self, bot):
        self.bot = bot
        utils.generate_leaderboard_image = _generate_leaderboard_image
        print(
            f"✅ [{COG_NAME}] v{VERSION} — generate_leaderboard_image patched. "
            f"{len(CATEGORIES)} categories, logo + GP per row."
        )

    async def cog_load(self):
        await utils.send_log(
            self.bot,
            f"🏆 **LeaderboardEngine v{VERSION}** loaded — "
            f"Logos + GP active. {len(CATEGORIES)} categories."
        )


async def setup(bot):
    await bot.add_cog(LeaderboardEngine(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
