import discord
from discord.ext import commands, tasks
from discord import app_commands
import utils
import asyncio
import aiohttp
from functools import partial

# ============================================================
# matches.py
# Version: 5.2.0
# Changelog:
#   v5.2.0 - FIX: Shared ID cache across all team iterations in
#             match_check_loop. Previously, get_all_match_ids() was
#             called once per team inside process_matches(), so the
#             same game could be logged N times (once per team_id
#             configured). Now IDs are fetched ONCE at the top of the
#             loop and passed as a shared list — if team A logs a game,
#             team B's pass through the same loop sees it as a duplicate
#             and skips it. Fixes all score/stat inflation.
#   v5.1.0 - Wrapped blocking Google Sheets calls in run_in_executor()
#             to prevent Discord heartbeat timeouts on 429 rate limits.
# ============================================================

VERSION = "5.3.0"

# --- INTERACTIVE DROPDOWN MENU ---
class MatchSelect(discord.ui.Select):
    def __init__(self, matches, cog):
        self.matches = matches
        self.cog = cog
        options = []
        
        # Discord limits dropdowns to 25 options
        for m in matches[:25]:
            mid = str(m['matchId'])
            c_ids = list(m['clubs'].keys())
            if len(c_ids) == 2:
                t1, t2 = m['clubs'][c_ids[0]], m['clubs'][c_ids[1]]
                label = f"{t1['details']['name']} {t1['score']} - {t2['score']} {t2['details']['name']}"
                desc = f"Match ID: {mid}"
            else:
                label = f"Match {mid}"
                desc = "Unknown Teams"
                
            options.append(discord.SelectOption(label=label[:100], description=desc[:100], value=mid))

        super().__init__(placeholder="Select a specific game to push...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_mid = self.values[0]
        
        # Find the specific match data from our fetched list
        selected_match = next((m for m in self.matches if str(m['matchId']) == selected_mid), None)
        
        if selected_match:
            await interaction.followup.send(f"⏳ Generating report for Match {selected_mid}...")
            # manual=True forces the graphic to generate even if the sheet already has it
            await self.cog.process_matches(interaction.channel, [selected_match], manual=True)
        else:
            await interaction.followup.send("❌ Could not process that match.")

class MatchView(discord.ui.View):
    def __init__(self, matches, cog):
        super().__init__()
        self.add_item(MatchSelect(matches, cog))

# --- MAIN COG ---
class Matches(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.match_check_loop.start()
        self.session = aiohttp.ClientSession()
        print(f"[LOG] ✅ matches.py v{VERSION} loaded — shared ID cache prevents duplicate logging.")

    def cog_unload(self):
        self.match_check_loop.cancel()
        asyncio.create_task(self.session.close())

    async def process_matches(self, channel, matches, manual=False, shared_ids=None):
        if not matches: return 0
        count = 0
        loop = asyncio.get_event_loop()

        # Use the shared ID cache if provided (passed from match_check_loop so
        # all team iterations share the same seen-set and can't double-log).
        # If not provided (e.g. manual pushgame), fetch fresh from the sheet.
        if shared_ids is None:
            ids = await loop.run_in_executor(None, utils.get_all_match_ids)
        else:
            ids = shared_ids
        
        for match in reversed(matches):
            mid = match['matchId']

            # Auto-scan only logs games where BOTH teams are monitored.
            # Prevents pre-season/scrimmage games vs non-league teams being recorded.
            # Manual /pushgame always bypasses this.
            if not manual:
                monitored = set(str(k) for k in self.bot.config.get("team_ids", {}).keys())
                if monitored:
                    game_club_ids = set(str(k) for k in match.get("clubs", {}).keys())
                    if not game_club_ids.issubset(monitored):
                        await utils.send_log(self.bot, f"⏭️ Skipped Match {mid} — opponent not in league.")
                        continue

            # --- FIX v5.1.0 ---
            # log_game_data also calls get_sheet() internally — run in executor.
            status = await loop.run_in_executor(
                None, partial(utils.log_game_data, match, self.bot.config, cached_ids=ids)
            )
            
            # If it's a duplicate and we are just auto-scanning, skip it silently
            if status == "Duplicate" and not manual: continue
            
            ids.append(mid)
            await utils.send_log(self.bot, f"📥 Processing Match {mid}...")
            
            try:
                img = utils.generate_game_report(match)
                if img and channel:
                    file = discord.File(img, filename=f"report_{mid}.png")
                    await channel.send(f"**Match Results:** {mid}", file=file)
                elif channel:
                    embed = utils.format_game_embed(match, self.bot.config)
                    await channel.send(embed=embed)
            except Exception as e: 
                await utils.send_log(self.bot, f"❌ Graphic Error: {e}")
            
            count += 1
            await asyncio.sleep(2)
            
        return count

    @tasks.loop(minutes=5)
    async def match_check_loop(self):
        cid = self.bot.config.get("announcement_channel_id")
        if not cid: return
        channel = self.bot.get_channel(int(cid))
        await utils.warm_up_session(self.session)
        
        await utils.send_log(self.bot, "🔄 Auto-Scanner: Checking for Private matches...")

        # FIX v5.2.0 — fetch the known ID list ONCE before iterating teams.
        # This single list is shared across all team iterations so if team A
        # logs a game, team B sees it in shared_ids and skips it as a duplicate.
        loop = asyncio.get_event_loop()
        shared_ids = await loop.run_in_executor(None, utils.get_all_match_ids)

        # Merge in any seeded IDs from scanner_manager window open
        # This prevents pre-window games from being picked up on first scan
        seeded = getattr(self, "_seeded_ids", set())
        for sid in seeded:
            if sid not in shared_ids:
                shared_ids.append(sid)

        for team_id in self.bot.config.get("team_ids", {}):
            try:
                matches = await utils.get_recent_games(self.session, team_id, self.bot.config['platform'], "club_private")
                if matches:
                    await self.process_matches(channel, matches, manual=False, shared_ids=shared_ids)
                await asyncio.sleep(5)
            except Exception as e:
                await utils.send_log(self.bot, f"⚠️ Loop Error: {e}")

    @match_check_loop.before_loop
    async def before_match_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="pushgame", description="Manually fetch games.")
    @app_commands.describe(match_type="Select the game type")
    @app_commands.choices(match_type=[
        app_commands.Choice(name="Public Match", value="gameType5"),
        app_commands.Choice(name="Playoffs", value="gameType10"),
        app_commands.Choice(name="Private Match", value="club_private")
    ])
    async def pushgame(self, interaction: discord.Interaction, club_name: str, match_type: str = "gameType5"):
        await interaction.response.defer()
        await utils.warm_up_session(self.session)
        
        cid = await utils.find_club(self.session, club_name, self.bot.config['platform'])
        if not cid: return await interaction.followup.send("❌ Club not found.")
        
        matches = await utils.get_recent_games(self.session, cid, self.bot.config['platform'], match_type)
        if not matches: return await interaction.followup.send("❌ No recent games found.")
        
        # INSTEAD OF PUSHING ALL, SEND THE DROPDOWN MENU
        view = MatchView(matches, self)
        await interaction.followup.send(f"Found {len(matches)} recent **{match_type}** games for {club_name}. Select one to push:", view=view)

async def setup(bot):
    await bot.add_cog(Matches(bot))
