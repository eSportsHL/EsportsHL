# ============================================================
#  Echelon League Bot — team_logos.py
#  Version: 1.2.0
#  NEW COG — Never modifies utils.py or any existing cog.
#  Provides:
#    - get_team_logo_url(team_name) -> str  (kept for compat)
#    - get_team_logo_image(team_name, size) -> PIL.Image | None
#    - /teamlogo <team> slash command
#    - /teamlist  slash command
#
#  Changelog:
#    v1.0.0 - Initial release. ESPN CDN logo map for all 32 NHL teams.
#    v1.1.0 - BUGFIX: Removed wait_until_ready() from cog_load().
#    v1.2.0 - Switched from ESPN CDN (blocking network) to local
#             ./logos/<id>.png files. Zero network calls at runtime.
#    v1.3.0 - Smarter _resolve_id(): strips league prefixes (SBHL,
#             RK, OS4, etc.) before matching. Word-by-word fallback
#             matching against all names and aliases.
#             Added defunct NHL teams: Quebec Nordiques, Hartford
#             Whalers, Minnesota North Stars, California Golden Seals,
#             Atlanta Thrashers. Custom teams return None silently.
# ============================================================

VERSION  = "1.3.0"
COG_NAME = "TeamLogos"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Local logo engine + prefix stripper")

import os
import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image

# ════════════════════════════════════════════════════════════
#  LOGO FOLDER
#  Expected: ./logos/<espn_id>.png  (e.g. tor.png, bos.png)
#  Path is relative to the project root (one level up from /cogs/)
# ════════════════════════════════════════════════════════════

LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logos")

# ════════════════════════════════════════════════════════════
#  TEAM ID MAP
# ════════════════════════════════════════════════════════════

NHL_LOGO_MAP = {
    "boston bruins":          "bos",
    "buffalo sabres":         "buf",
    "detroit red wings":      "det",
    "florida panthers":       "fla",
    "montreal canadiens":     "mtl",
    "montréal canadiens":     "mtl",
    "ottawa senators":        "ott",
    "tampa bay lightning":    "tb",
    "toronto maple leafs":    "tor",
    "carolina hurricanes":    "car",
    "columbus blue jackets":  "cbj",
    "new jersey devils":      "njd",
    "new york islanders":     "nyi",
    "new york rangers":       "nyr",
    "philadelphia flyers":    "phi",
    "pittsburgh penguins":    "pit",
    "washington capitals":    "wsh",
    "arizona coyotes":        "ari",
    "chicago blackhawks":     "chi",
    "colorado avalanche":     "col",
    "dallas stars":           "dal",
    "minnesota wild":         "min",
    "nashville predators":    "nsh",
    "st. louis blues":        "stl",
    "st louis blues":         "stl",
    "utah mammoth":           "utah",
    "anaheim ducks":          "ana",
    "calgary flames":         "cgy",
    "edmonton oilers":        "edm",
    "los angeles kings":      "lak",
    "san jose sharks":        "sjs",
    "seattle kraken":         "sea",
    "vancouver canucks":      "van",
    "vegas golden knights":   "vgk",
    "winnipeg jets":          "wpg",

    # ── Defunct / Historical ─────────────────────────────────
    # These map to the closest current or legacy ESPN logo ID.
    # Add the PNG files to ./logos/ using download_logos.py or manually.
    "quebec nordiques":       "col",   # Nordiques -> Avalanche lineage
    "hartford whalers":       "car",   # Whalers -> Hurricanes lineage
    "minnesota north stars":  "dal",   # North Stars -> Stars lineage
    "north stars":            "dal",
    "california golden seals":"sjs",   # Golden Seals -> Sharks (closest)
    "golden seals":           "sjs",
    "atlanta thrashers":      "wpg",   # Thrashers -> Jets lineage
    "thrashers":              "wpg",
    "phoenix coyotes":        "ari",   # Phoenix -> Arizona
}

NHL_ALIASES = {
    "bos": "boston bruins",       "buf": "buffalo sabres",
    "det": "detroit red wings",   "fla": "florida panthers",
    "mtl": "montreal canadiens",  "ott": "ottawa senators",
    "tb":  "tampa bay lightning", "tbl": "tampa bay lightning",
    "tor": "toronto maple leafs", "car": "carolina hurricanes",
    "cbj": "columbus blue jackets","njd": "new jersey devils",
    "nyi": "new york islanders",  "nyr": "new york rangers",
    "phi": "philadelphia flyers", "pit": "pittsburgh penguins",
    "wsh": "washington capitals", "wdc": "washington capitals",
    "ari": "arizona coyotes",     "chi": "chicago blackhawks",
    "col": "colorado avalanche",  "dal": "dallas stars",
    "min": "minnesota wild",      "nsh": "nashville predators",
    "stl": "st. louis blues",     "ana": "anaheim ducks",
    "cgy": "calgary flames",      "edm": "edmonton oilers",
    "lak": "los angeles kings",   "sjs": "san jose sharks",
    "sea": "seattle kraken",      "van": "vancouver canucks",
    "vgk": "vegas golden knights","wpg": "winnipeg jets",
    "utah": "utah mammoth",
    "bruins":         "boston bruins",
    "sabres":         "buffalo sabres",
    "redwings":       "detroit red wings",
    "red wings":      "detroit red wings",
    "panthers":       "florida panthers",
    "habs":           "montreal canadiens",
    "canadiens":      "montreal canadiens",
    "senators":       "ottawa senators",
    "sens":           "ottawa senators",
    "lightning":      "tampa bay lightning",
    "bolts":          "tampa bay lightning",
    "leafs":          "toronto maple leafs",
    "maple leafs":    "toronto maple leafs",
    "hurricanes":     "carolina hurricanes",
    "canes":          "carolina hurricanes",
    "blue jackets":   "columbus blue jackets",
    "jackets":        "columbus blue jackets",
    "devils":         "new jersey devils",
    "islanders":      "new york islanders",
    "isles":          "new york islanders",
    "rangers":        "new york rangers",
    "flyers":         "philadelphia flyers",
    "penguins":       "pittsburgh penguins",
    "pens":           "pittsburgh penguins",
    "capitals":       "washington capitals",
    "caps":           "washington capitals",
    "coyotes":        "arizona coyotes",
    "yotes":          "arizona coyotes",
    "blackhawks":     "chicago blackhawks",
    "hawks":          "chicago blackhawks",
    "avalanche":      "colorado avalanche",
    "avs":            "colorado avalanche",
    "stars":          "dallas stars",
    "wild":           "minnesota wild",
    "predators":      "nashville predators",
    "preds":          "nashville predators",
    "blues":          "st. louis blues",
    "ducks":          "anaheim ducks",
    "flames":         "calgary flames",
    "oilers":         "edmonton oilers",
    "kings":          "los angeles kings",
    "sharks":         "san jose sharks",
    "kraken":         "seattle kraken",
    "canucks":        "vancouver canucks",
    "golden knights": "vegas golden knights",
    "knights":        "vegas golden knights",
    "jets":           "winnipeg jets",
    "mammoth":        "utah mammoth",

    # Defunct / historical nicknames
    "nordiques":      "quebec nordiques",
    "whalers":        "hartford whalers",
    "north stars":    "minnesota north stars",
    "northstars":     "minnesota north stars",
    "golden seals":   "california golden seals",
    "seals":          "california golden seals",
    "thrashers":      "atlanta thrashers",
}

ESPN_CDN = "https://a.espncdn.com/i/teamlogos/nhl/500/{}.png"

# ════════════════════════════════════════════════════════════
#  ID RESOLVER
# ════════════════════════════════════════════════════════════

# League prefixes to strip before matching.
# Add any new prefixes your league uses here.
_STRIP_PREFIXES = {
    "sbhl", "rk", "os4", "echelon", "nhl", "ahl", "the",
}

def _resolve_id(team_name: str) -> str | None:
    """
    Resolve a team name to an ESPN logo ID.
    Handles:
      - Exact matches:           "anaheim ducks"       -> "ana"
      - Alias matches:           "ducks"               -> "ana"
      - Prefix-stripped:         "sbhl anaheim ducks"  -> "ana"
      - Word-in-name:            "blackhawks sbhl"     -> "chi"
      - Any-word alias match:    "sbhl buffalo"        -> "buf"
    Returns None for custom/fictional teams with no NHL match.
    """
    key = team_name.strip().lower()

    # 1. Direct match
    if key in NHL_LOGO_MAP:
        return NHL_LOGO_MAP[key]

    # 2. Alias match
    if key in NHL_ALIASES:
        full = NHL_ALIASES[key]
        return NHL_LOGO_MAP.get(full)

    # 3. Strip known league prefixes and retry
    words = key.split()
    stripped_words = [w for w in words if w not in _STRIP_PREFIXES]
    stripped = " ".join(stripped_words)

    if stripped and stripped != key:
        if stripped in NHL_LOGO_MAP:
            return NHL_LOGO_MAP[stripped]
        if stripped in NHL_ALIASES:
            full = NHL_ALIASES[stripped]
            return NHL_LOGO_MAP.get(full)

    # 4. Check if any word in the name is a known alias
    for word in stripped_words:
        if word in NHL_ALIASES:
            full = NHL_ALIASES[word]
            return NHL_LOGO_MAP.get(full)
        if word in NHL_LOGO_MAP:
            return NHL_LOGO_MAP[word]

    # 5. Substring match against full team names (e.g. "redwings" in "detroit red wings")
    for full_name, cdn_id in NHL_LOGO_MAP.items():
        if stripped and stripped in full_name:
            return cdn_id
        # Also check if any significant word from the input appears in the full name
        for word in stripped_words:
            if len(word) >= 4 and word in full_name:
                return cdn_id

    return None

# ════════════════════════════════════════════════════════════
#  PUBLIC: URL  (backwards compat)
# ════════════════════════════════════════════════════════════

def get_team_logo_url(team_name: str) -> str | None:
    cdn_id = _resolve_id(team_name)
    return ESPN_CDN.format(cdn_id) if cdn_id else None

# ════════════════════════════════════════════════════════════
#  PUBLIC: LOCAL IMAGE LOAD
#  Called by image_engine.py inside run_in_executor.
#  Pure disk I/O — no network, no async needed.
#  Cached after first load so repeated calls are instant.
# ════════════════════════════════════════════════════════════

_logo_cache: dict = {}

def get_team_logo_image(team_name: str, size: int = 48) -> "Image.Image | None":
    """
    Load ./logos/<id>.png and return a resized PIL RGBA Image.
    Returns None silently if file doesn't exist.
    """
    cdn_id = _resolve_id(team_name)
    if not cdn_id:
        return None

    cache_key = f"{cdn_id}:{size}"
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]

    path = os.path.join(LOGO_DIR, f"{cdn_id}.png")
    if not os.path.exists(path):
        print(f"[{COG_NAME}] Logo not found: {path}")
        _logo_cache[cache_key] = None
        return None

    try:
        logo = Image.open(path).convert("RGBA")
        logo = logo.resize((size, size), Image.LANCZOS)
        _logo_cache[cache_key] = logo
        return logo
    except Exception as e:
        print(f"[{COG_NAME}] Failed to load logo '{path}': {e}")
        _logo_cache[cache_key] = None
        return None


def get_all_teams() -> list[str]:
    return sorted(NHL_LOGO_MAP.keys())


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class TeamLogos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if os.path.isdir(LOGO_DIR):
            count = len([f for f in os.listdir(LOGO_DIR) if f.endswith(".png")])
            print(f"✅ [{COG_NAME}] v{VERSION} — {count} logos found in {LOGO_DIR}")
        else:
            print(f"⚠️  [{COG_NAME}] v{VERSION} — Logo folder not found: {LOGO_DIR}")

    # NOTE: cog_load() intentionally omitted.
    # wait_until_ready() inside cog_load() blocks the load sequence and crashes the bot.

    @app_commands.command(name="teamlogo", description="Display the NHL team logo for any team")
    @app_commands.describe(team="Team name, nickname, or abbreviation (e.g. 'leafs', 'TOR')")
    async def teamlogo(self, interaction: discord.Interaction, team: str):
        await interaction.response.defer()

        cdn_id = _resolve_id(team)
        if not cdn_id:
            await interaction.followup.send(
                f"❌ Could not find a logo for **{team}**.\n"
                f"Try a full name like `Toronto Maple Leafs`, nickname like `leafs`, or abbreviation like `TOR`."
            )
            return

        local_path = os.path.join(LOGO_DIR, f"{cdn_id}.png")
        if os.path.exists(local_path):
            file = discord.File(local_path, filename=f"{cdn_id}.png")
            embed = discord.Embed(title=f"🏒 {team.title()}", color=discord.Color.from_str("#58a6ff"))
            embed.set_image(url=f"attachment://{cdn_id}.png")
            embed.set_footer(text=f"Echelon League Bot v{VERSION} • Local")
            await interaction.followup.send(embed=embed, file=file)
        else:
            embed = discord.Embed(title=f"🏒 {team.title()}", color=discord.Color.from_str("#58a6ff"))
            embed.set_image(url=ESPN_CDN.format(cdn_id))
            embed.set_footer(text=f"Echelon League Bot v{VERSION} • ESPN CDN fallback")
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="teamlist", description="List all NHL teams supported by the logo engine")
    async def teamlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        teams  = get_all_teams()
        chunks = [teams[i:i+11] for i in range(0, len(teams), 11)]
        embed  = discord.Embed(
            title="🏒 NHL Teams — Logo Engine",
            description="Use `/teamlogo` with any full name, nickname, or abbreviation.",
            color=discord.Color.from_str("#58a6ff")
        )
        col_names = ["Atlantic / Metro", "Central / Pacific", "Central / Pacific (cont.)"]
        for i, chunk in enumerate(chunks):
            embed.add_field(
                name=col_names[i] if i < len(col_names) else "Teams",
                value="\n".join(t.title() for t in chunk),
                inline=True
            )
        embed.set_footer(text=f"Echelon League Bot v{VERSION} • {len(teams)} teams loaded")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TeamLogos(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
