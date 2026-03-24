import discord
from discord.ext import commands
import aiohttp
from datetime import datetime   # ← FIX: was calling utils.datetime which doesn't exist
import utils

# ============================================================
# league_manager.py
# Version: 1.1.0
# Changelog:
#   v1.1.0 - BUGFIX: utils.datetime does not exist as an attribute.
#             Added `from datetime import datetime` and replaced
#             utils.datetime.now() with datetime.now(). The previous
#             version crashed immediately on !scrape_all_stats.
#   v1.0.0 - Initial release. !scrape_all_stats deep-dumps every
#             available EA API field to a Full_API_Dump sheet tab.
# ============================================================

VERSION  = "1.1.0"
COG_NAME = "LeagueManager"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading")


class LeagueManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...',
            'Referer': 'https://www.ea.com/',
            'Accept': 'application/json'
        }
        self.platform = self.bot.config.get("platform", "common-gen5")

    async def fetch_full_stats(self, session, member_name):
        """Fetches the complete JSON dictionary for a player."""
        url = "https://proclubs.ea.com/api/nhl/members/search"
        params = {'platform': self.platform, 'memberName': member_name}
        async with session.get(url, params=params) as r:
            if r.status == 200:
                data = await r.json()
                return data['members'][0] if data.get('members') else None
        return None

    @commands.command(name="scrape_all_stats")
    @commands.has_permissions(administrator=True)
    async def scrape_all_stats(self, ctx, *, player_name: str):
        """Scrapes every available EA stat and resolves Team Names."""
        await ctx.send(f"🔍 Fetching deep-stats for `{player_name}`...")

        async with aiohttp.ClientSession(headers=self.headers) as session:
            raw_data = await self.fetch_full_stats(session, player_name)

            if not raw_data:
                return await ctx.send("❌ Player not found.")

            # 1. Resolve Team ID to Name
            team_id   = str(raw_data.get('clubId', '0'))
            team_name = self.bot.config.get("team_ids", {}).get(team_id, f"Unknown ({team_id})")

            # 2. Dynamically build headers and values for EVERY stat
            headers = ["Timestamp", "Player Name", "Team Name"]
            values  = [datetime.now().strftime("%Y-%m-%d %H:%M"), player_name, team_name]

            for key, val in raw_data.items():
                if key not in ['clubId']:   # Avoid duplicate columns
                    headers.append(key)
                    values.append(val)

            # 3. Write to Google Sheets
            sh = utils.get_sheet()
            try:
                try:
                    ws = sh.worksheet("Full_API_Dump")
                except Exception:
                    ws = sh.add_worksheet("Full_API_Dump", 1000, len(headers))

                if not ws.get_all_values():
                    ws.append_row(headers)   # Add header if empty
                ws.append_row(values)
                await ctx.send(f"✅ Recorded all stats for **{player_name}** ({team_name})!")
            except Exception as e:
                await ctx.send(f"❌ Sheets Error: {e}")


async def setup(bot):
    await bot.add_cog(LeagueManager(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
