__version__ = "35.8-FINAL-JSON-BRIDGE"

import os, json, asyncio, aiohttp, io, discord
from discord.ext import commands
from discord import app_commands

class HockeySearch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.PLATFORM = "common-gen5"
        self.HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.ea.com/',
            'Origin': 'https://www.ea.com',
            'Connection': 'keep-alive'
        }

    # --- 🏆 EA API HELPERS ---

    async def fetch_ea_data(self, session, name):
        # 1. Try Player Search First
        p_url = "https://proclubs.ea.com/api/nhl/members/search"
        try:
            async with session.get(p_url, params={'platform': self.PLATFORM, 'memberName': name}) as r:
                if r.status == 200:
                    p_res = await r.json()
                    if p_res and p_res.get('members'):
                        return p_res['members'][0], "Player"
        except Exception:
            pass

        # 2. Try Team Search if Player fails
        t_url = "https://proclubs.ea.com/api/nhl/clubs/search"
        try:
            async with session.get(t_url, params={'platform': self.PLATFORM, 'clubName': name}) as r:
                if r.status == 200:
                    t_res = await r.json()
                    if t_res:
                        # Grab the first matching team and inject its ID into the data
                        team_id = list(t_res.keys())[0]
                        team_data = t_res[team_id]
                        team_data['club_id_internal'] = team_id
                        return team_data, "Team"
        except Exception:
            pass

        return None, None

    # --- 🤖 SLASH COMMANDS ---

    @app_commands.command(name="hockey", description="Professional EA Pro Clubs Stats Search")
    async def hockey(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        async with aiohttp.ClientSession(headers=self.HEADERS) as session:
            data, mode = await self.fetch_ea_data(session, query)
            if not data:
                return await interaction.followup.send(f"❌ '{query}' not found.")
            
            # --- HELPER FOR BOTH MODES ---
            data_lower = {k.lower(): v for k, v in data.items()}
            def get_s(*keys):
                for k in keys:
                    val = data_lower.get(k.lower())
                    if val is not None and val != "":
                        try:
                            num = float(val)
                            return int(num) if num.is_integer() else num
                        except: 
                            return val
                return 0

            if mode == "Player":
                name_title = data.get('playername', data.get('skplayername', 'Unknown')).upper()
                embed = discord.Embed(title=f"🏒 {name_title}", color=discord.Color.blue(), timestamp=interaction.created_at)
                
                gp = get_s('gamesplayed', 'skgamesplayed', 'glgamesplayed')
                totals = [
                    f"**Games Played:** `{gp}`",
                    f"**Goals:** `{get_s('skgoals', 'goals')}`",
                    f"**Assists:** `{get_s('skassists', 'assists')}`",
                    f"**Points:** `{get_s('skgoals', 'goals') + get_s('skassists', 'assists')}`",
                    f"**+/-:** `{get_s('plusmin', 'skplusmin')}`",
                    f"**PIM:** `{get_s('pim', 'skpim')}`",
                    f"**Hits:** `{get_s('skhits', 'hits')}`"
                ]
                embed.add_field(name="📊 Skater Totals", value="\n".join(totals), inline=False)
                
                if get_s('glgamesplayed') > 0 or get_s('glsaves', 'saves') > 0:
                    goalie = [
                        f"**Saves:** `{get_s('glsaves', 'saves')}`",
                        f"**Save %:** `{get_s('glsavepct', 'savepct')}%`",
                        f"**GAA:** `{get_s('glgaa', 'gaa')}`",
                        f"**Shutouts:** `{get_s('glshutouts', 'glsoperiods')}`"
                    ]
                    embed.add_field(name="🥅 Goalie Stats", value="\n".join(goalie), inline=False)

            else:  # --- TEAM MODE ---
                team_name = data.get('name', 'Unknown Team').upper()
                club_id = data.get('club_id_internal', 'N/A')
                embed = discord.Embed(title=f"🏢 {team_name}", color=discord.Color.green(), timestamp=interaction.created_at)
                
                # Highlight the Club ID for easy copying
                embed.description = f"**Club ID:** `{club_id}`"
                
                record = [
                    f"**Record:** `{get_s('wins')}-{get_s('losses')}-{get_s('ties')}`",
                    f"**Goals For:** `{get_s('goals')}`",
                    f"**Goals Against:** `{get_s('goalsagainst')}`",
                    f"**Current Div:** `{get_s('currentdivision')}`",
                    f"**Best Div:** `{get_s('bestdivision')}`"
                ]
                embed.add_field(name="📊 Club Record", value="\n".join(record), inline=False)

            embed.set_footer(text=f"ESHL League API • v{__version__} | Search: {query}")
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(HockeySearch(bot))
