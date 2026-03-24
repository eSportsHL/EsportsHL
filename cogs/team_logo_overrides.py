# ============================================================
#  Echelon League Bot — team_logo_overrides.py
#  Version: 1.1.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Provides:
#    - /setteamlogo <team_name> <logo>  — assign a logo to any team
#    - /removeteamlogo <team_name>      — remove a manual override
#    - /listteamlogos                   — show all current overrides
#
#  Changelog:
#    v1.0.0 - Initial release. Slash commands for manual logo
#             assignment. Persists to logo_overrides.json.
#    v1.1.0 - /setteamlogo accepts custom filenames directly.
#    v1.2.0 - BUGFIX: Custom disk files now checked BEFORE NHL
#             resolver. Previously "seals" resolved to "sjs" via
#             the NHL alias map before seals.png could be used.
# ============================================================

VERSION  = "1.2.0"
COG_NAME = "TeamLogoOverrides"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — Manual logo assignment")

import os
import json
import discord
from discord.ext import commands
from discord import app_commands

# ════════════════════════════════════════════════════════════
#  OVERRIDES FILE
#  Stored at project root: ./logo_overrides.json
#  Format: { "rk rat kings": "rat", "rk jasper grizzlies": "van" }
# ════════════════════════════════════════════════════════════

OVERRIDES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "logo_overrides.json"
)

def _load_overrides() -> dict:
    try:
        with open(OVERRIDES_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[{COG_NAME}] Failed to load overrides: {e}")
        return {}

def _save_overrides(data: dict):
    try:
        with open(OVERRIDES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[{COG_NAME}] Failed to save overrides: {e}")

_overrides: dict = _load_overrides()

def get_override(team_name: str) -> str | None:
    return _overrides.get(team_name.strip().lower())


# ════════════════════════════════════════════════════════════
#  PATCH team_logos._resolve_id() AT LOAD TIME
# ════════════════════════════════════════════════════════════

def _patch_team_logos():
    try:
        import cogs.team_logos as tl
        _original_resolve = tl._resolve_id

        def _patched_resolve(team_name: str) -> str | None:
            override = get_override(team_name)
            if override:
                return override
            return _original_resolve(team_name)

        tl._resolve_id = _patched_resolve
        print(f"  ✔ [{COG_NAME}] Patched team_logos._resolve_id() — overrides active")
    except Exception as e:
        print(f"  ✘ [{COG_NAME}] Failed to patch team_logos: {e}")


# ════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════

class TeamLogoOverrides(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _patch_team_logos()
        print(f"✅ [{COG_NAME}] v{VERSION} — {len(_overrides)} override(s) loaded")

    # ── /setteamlogo ──────────────────────────────────────────
    @app_commands.command(
        name="setteamlogo",
        description="Assign a logo to any team name"
    )
    @app_commands.describe(
        team_name="Exact team name as it appears in standings/roster (e.g. 'RK Rat Kings')",
        logo="Custom filename without .png OR NHL name/abbrev (e.g. 'seals', 'rat', 'canucks', 'VAN')"
    )
    @app_commands.default_permissions(administrator=True)
    async def setteamlogo(self, interaction: discord.Interaction,
                          team_name: str, logo: str):
        await interaction.response.defer(ephemeral=True)

        try:
            from cogs.team_logos import _resolve_id, LOGO_DIR
        except Exception as e:
            await interaction.followup.send(f"❌ Could not load team_logos cog: {e}")
            return

        candidate = logo.strip().lower()
        custom_path = os.path.join(LOGO_DIR, f"{candidate}.png")

        # Step 1 — check if ./logos/<logo>.png exists on disk FIRST.
        # This ensures custom files like seals.png always win over NHL resolver
        # which might map "seals" -> "sjs" before we get a chance to use the file.
        if os.path.exists(custom_path):
            cdn_id = candidate

        # Step 2 — no custom file found, try NHL team name resolver
        else:
            cdn_id = _resolve_id(logo)
            if not cdn_id:
                await interaction.followup.send(
                    f"❌ `{logo}` didn't match any known NHL team and "
                    f"`./logos/{candidate}.png` was not found on disk.\n\n"
                    f"**Options:**\n"
                    f"• Use a custom filename: drop `{candidate}.png` into `./logos/` first\n"
                    f"• Use an NHL name: `canucks`, `VAN`, `Vancouver Canucks`"
                )
                return

        logo_path = os.path.join(LOGO_DIR, f"{cdn_id}.png")
        file_exists = os.path.exists(logo_path)

        # Save override and clear cache
        key = team_name.strip().lower()
        _overrides[key] = cdn_id
        _save_overrides(_overrides)

        try:
            import cogs.team_logos as tl
            stale = [k for k in tl._logo_cache
                     if k.startswith(f"{cdn_id}:") or k.startswith(f"{key}:")]
            for k in stale:
                del tl._logo_cache[k]
        except Exception:
            pass

        status = "✅ File found" if file_exists else "⚠️ File not found in ./logos/ — images will skip this logo"

        embed = discord.Embed(
            title="🏒 Logo Override Set",
            color=discord.Color.from_str("#3fb950")
        )
        embed.add_field(name="Team",        value=team_name,         inline=True)
        embed.add_field(name="Logo File",   value=f"`{cdn_id}.png`", inline=True)
        embed.add_field(name="File Status", value=status,            inline=False)
        embed.set_footer(text=f"Echelon League Bot • TeamLogoOverrides v{VERSION}")

        if file_exists:
            file = discord.File(logo_path, filename=f"{cdn_id}.png")
            embed.set_thumbnail(url=f"attachment://{cdn_id}.png")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)

    # ── /removeteamlogo ───────────────────────────────────────
    @app_commands.command(
        name="removeteamlogo",
        description="Remove a manual logo override for a team"
    )
    @app_commands.describe(team_name="The team name whose override you want to remove")
    @app_commands.default_permissions(administrator=True)
    async def removeteamlogo(self, interaction: discord.Interaction, team_name: str):
        await interaction.response.defer(ephemeral=True)

        key = team_name.strip().lower()
        if key not in _overrides:
            await interaction.followup.send(
                f"❌ No override found for **{team_name}**.\n"
                f"Use `/listteamlogos` to see current overrides."
            )
            return

        old_id = _overrides.pop(key)
        _save_overrides(_overrides)
        await interaction.followup.send(
            f"✅ Removed logo override for **{team_name}** (was `{old_id}.png`)."
        )

    # ── /listteamlogos ────────────────────────────────────────
    @app_commands.command(
        name="listteamlogos",
        description="Show all manually assigned team logo overrides"
    )
    async def listteamlogos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _overrides:
            await interaction.followup.send(
                "No manual logo overrides set.\n"
                "Use `/setteamlogo` to assign logos to custom teams."
            )
            return

        embed = discord.Embed(
            title="🏒 Team Logo Overrides",
            description=f"{len(_overrides)} manual assignment(s)",
            color=discord.Color.from_str("#58a6ff")
        )
        lines = [f"`{team}` → `{logo_id}.png`"
                 for team, logo_id in sorted(_overrides.items())]
        chunk_size = 15
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i+chunk_size]
            embed.add_field(
                name=f"Overrides {i+1}–{i+len(chunk)}",
                value="\n".join(chunk),
                inline=False
            )
        embed.set_footer(text=f"Echelon League Bot • TeamLogoOverrides v{VERSION}")
        await interaction.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════
#  SETUP
# ════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(TeamLogoOverrides(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
