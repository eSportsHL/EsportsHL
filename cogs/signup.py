import discord
from discord import ui, app_commands
from discord.ext import commands
import json
import os
import utils  # Uses your existing utils.py for sheet access

# --- CONFIGURATION ---
POSITIONS = ["C", "RW", "LW", "LD", "RD", "G"]
MEMBER_ROLE_NAME = "Registered"
STATS_DIR = "./stats"
SIGNUPS_FILE = f"{STATS_DIR}/signups.json"

# --- DATA HANDLING ---
def ensure_stats_dir():
    if not os.path.exists(STATS_DIR):
        os.makedirs(STATS_DIR)

def save_to_stats(data: dict):
    ensure_stats_dir()
    signups = []
    if os.path.exists(SIGNUPS_FILE):
        with open(SIGNUPS_FILE, 'r') as f:
            try:
                signups = json.load(f)
            except json.JSONDecodeError:
                signups = []
    
    # Remove existing entry to update with fresh info
    existing = next((s for s in signups if s['user_id'] == data['user_id']), None)
    if existing:
        signups.remove(existing)
    
    signups.append(data)
    with open(SIGNUPS_FILE, 'w') as f:
        json.dump(signups, f, indent=4)

# --- UI COMPONENTS ---

class SignupModal(ui.Modal, title='TextBook Player Registration'):
    gamertag = ui.TextInput(
        label="Gamertag / PSN ID", 
        placeholder="Enter your EA ID here...", 
        required=True,
        min_length=3,
        max_length=20
    )
    availability = ui.TextInput(
        label="Availability (Days per week)", 
        placeholder="e.g. Mon-Fri, 4 days, etc.", 
        required=True,
        style=discord.TextStyle.short
    )

    def __init__(self, positions):
        super().__init__()
        self.positions = positions

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Local JSON Save
        data = {
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "gamertag": self.gamertag.value,
            "positions": self.positions,
            "availability": self.availability.value
        }
        save_to_stats(data)

        # 2. Google Sheets Auto-Creation & Sync
        try:
            sh = utils.get_sheet()
            if sh:
                try:
                    ws = sh.worksheet("Signups")
                except:
                    # BOT CREATE: Creates the tab if it doesn't exist
                    ws = sh.add_worksheet("Signups", 100, 5)
                    ws.append_row(["Discord Name", "Discord ID", "EA ID", "Positions", "Availability"])
                    # Format headers to bold
                    ws.format("A1:E1", {"textFormat": {"bold": True}})

                # Find user by Discord ID to prevent duplicates
                cells = ws.findall(str(interaction.user.id))
                row_data = [
                    str(interaction.user),
                    str(interaction.user.id),
                    self.gamertag.value,
                    ", ".join(self.positions),
                    self.availability.value
                ]

                if cells:
                    row_index = cells[0].row
                    ws.update(f"A{row_index}:E{row_index}", [row_data])
                else:
                    ws.append_row(row_data)
        except Exception as e:
            print(f"Sheet Sync Error: {e}")

        # 3. Role Assignment
        role = discord.utils.get(interaction.guild.roles, name=MEMBER_ROLE_NAME)
        if role:
            try: await interaction.user.add_roles(role)
            except: pass

        await interaction.response.send_message(
            f"✅ **Registration Complete!**\nSynced to Scout Board and JSON database.", 
            ephemeral=True
        )

class PositionSelect(ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=pos) for pos in POSITIONS]
        super().__init__(
            placeholder="Select your preferred positions...",
            min_values=1,
            max_values=3,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SignupModal(self.values))

class WelcomeView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PositionSelect())

class Signup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setup_signup")
    @commands.has_permissions(administrator=True)
    async def setup_signup(self, ctx):
        embed = discord.Embed(
            title="🏒 League Player Registration",
            description="Select your positions and fill out the form to register.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=WelcomeView())

    @app_commands.command(name="signup", description="Register for the league")
    async def signup(self, interaction: discord.Interaction):
        await interaction.response.send_message("Please select your positions:", view=WelcomeView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Signup(bot))
