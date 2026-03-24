import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import utils

# ============================================================
#  OS4 League Bot — draft.py
#  Version: 1.1.0  —  Added custom_ids for persistent view
#  Fix: DraftBoardView now survives bot restarts
# ============================================================

VERSION = "1.1.0"
COG_NAME = "DraftBoard"

print(f"📦 [{COG_NAME}] v{VERSION} loaded")

# --- CONFIGURATION ---
SIGNUPS_FILE = "./stats/signups.json"
ROSTER_DB_FILE = os.path.join(utils.BASE_DIR, 'rosters.json')

POS_EMOJIS = {
    "C": "🏒", "LW": "🏒", "RW": "🏒",
    "LD": "🛡️", "RD": "🛡️", "G": "🥅"
}

def get_free_agents():
    if not os.path.exists(SIGNUPS_FILE): return []
    with open(SIGNUPS_FILE, 'r') as f:
        try: players = json.load(f)
        except: return []
    
    signed_ids = []
    if os.path.exists(ROSTER_DB_FILE):
        with open(ROSTER_DB_FILE, 'r') as f:
            try: signed_ids = [str(k) for k in json.load(f).keys()]
            except: pass
    
    return [p for p in players if str(p['user_id']) not in signed_ids]

def create_board_embed(free_agents):
    embed = discord.Embed(
        title="🏆  Elite Scouting Hub", 
        description="*Browse available prospects. Select a name below for full career stats.*",
        color=0x5865F2
    )
    
    if not free_agents:
        embed.description = "🚫 **No Free Agents Currently Available.**"
        return embed

    list_content = ""
    for p in free_agents[:15]:
        primary_pos = p['positions'][0] if p['positions'] else "N/A"
        emoji = POS_EMOJIS.get(primary_pos, "🏒")
        gt = p['gamertag']
        avail = p['availability']
        list_content += f"{emoji} **{gt}** • `{primary_pos}` • *Avail: {avail}*\n"
    
    embed.add_field(name="Available Talent", value=list_content, inline=False)
    embed.set_footer(text=f"Total Unsigned: {len(free_agents)} • 🔄 Use Refresh to update")
    return embed

# --- PROXY SYSTEM (Prevents Read-Only/Double Response Errors) ---

class ProxyResponse:
    def __init__(self, proxy): self.proxy = proxy
    async def defer(self, *args, **kwargs): pass
    def is_done(self): return True
    async def send_message(self, *args, **kwargs): await self.proxy.followup.send(*args, **kwargs)

class ProxyFollowup:
    def __init__(self, proxy): self.proxy = proxy
    async def send(self, *args, **kwargs):
        view = discord.ui.View(timeout=None)
        view.add_item(BackButton(self.proxy._players))
        kwargs.pop('ephemeral', None) 
        kwargs['view'] = view
        await self.proxy._interaction.edit_original_response(**kwargs)

class ProxyInteraction:
    def __init__(self, interaction, players):
        self._interaction = interaction
        self._players = players
        self.response = ProxyResponse(self)
        self.followup = ProxyFollowup(self)
        self.user = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.client = interaction.client
    def __getattr__(self, name): return getattr(self._interaction, name)

# --- UI COMPONENTS ---

class RefreshButton(discord.ui.Button):
    def __init__(self):
        # custom_id required for persistent view across restarts
        super().__init__(label="Refresh List", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="draft_refresh")

    async def callback(self, interaction: discord.Interaction):
        fa = get_free_agents()
        await interaction.response.edit_message(embed=create_board_embed(fa), view=DraftBoardView(fa))

class BackButton(discord.ui.Button):
    def __init__(self, players):
        # custom_id required for persistent view across restarts
        super().__init__(label="Back to List", style=discord.ButtonStyle.gray, emoji="⬅️", custom_id="draft_back")
        self.players = players

    async def callback(self, interaction: discord.Interaction):
        fa = get_free_agents()
        await interaction.response.edit_message(embed=create_board_embed(fa), view=DraftBoardView(fa))

class PlayerStatsSelect(discord.ui.Select):
    def __init__(self, players):
        options = [
            discord.SelectOption(
                label=p['gamertag'][:25], 
                value=p['gamertag'],
                emoji=POS_EMOJIS.get(p['positions'][0], "🏒") if p['positions'] else "🏒"
            ) for p in players
        ]
        # custom_id required for persistent view across restarts
        super().__init__(placeholder="🔍 Choose a prospect to scout...", options=options, custom_id="draft_player_select")

    async def callback(self, interaction: discord.Interaction):
        hockey_cog = interaction.client.get_cog("HockeySearch")
        if not hockey_cog: return await interaction.response.send_message("❌ Error.", ephemeral=True)

        await interaction.response.defer()
        proxy = ProxyInteraction(interaction, self.view.players)
        try:
            await hockey_cog.hockey.callback(hockey_cog, proxy, self.values[0])
        except Exception as e:
            print(f"Error: {e}")

class DraftBoardView(discord.ui.View):
    def __init__(self, players):
        super().__init__(timeout=None)
        self.players = players
        if players: self.add_item(PlayerStatsSelect(players[:25]))
        self.add_item(RefreshButton())

class DraftBoard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print(f"🏒 [{COG_NAME}] Cog initialized — v{VERSION}")

    @app_commands.command(name="draftboard", description="Clean Interactive Scouting Board")
    async def draftboard(self, interaction: discord.Interaction):
        fa = get_free_agents()
        await interaction.response.send_message(embed=create_board_embed(fa), view=DraftBoardView(fa))

async def setup(bot):
    await bot.add_cog(DraftBoard(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
