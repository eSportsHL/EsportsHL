import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import utils

# We will use a separate DB just for roster assignments, 
# and read the gamertags from your existing signups.json
ROSTER_DB_FILE = os.path.join(utils.BASE_DIR, 'rosters.json')
SIGNUPS_FILE = "./stats/signups.json" # Matching your signup.py path
MANAGER_ROLES = ["Owner", "GM", "AGM"]

def load_rosters():
    if not os.path.exists(ROSTER_DB_FILE): return {}
    with open(ROSTER_DB_FILE, 'r') as f: return json.load(f)

def save_rosters(data):
    with open(ROSTER_DB_FILE, 'w') as f: json.dump(data, f, indent=4)

def get_signup_data(user_id: int):
    """Fetches player data from your signup.py generated JSON."""
    if not os.path.exists(SIGNUPS_FILE): return None
    with open(SIGNUPS_FILE, 'r') as f:
        signups = json.load(f)
    return next((s for s in signups if s['user_id'] == user_id), None)

def get_manager_team(member: discord.Member, config_teams: dict):
    """Checks if the user is a manager, and returns their team name and ID."""
    is_manager = any(role.name in MANAGER_ROLES for role in member.roles)
    if not is_manager:
        return None, None
        
    # Find which configured team role the manager possesses
    for tid, tname in config_teams.items():
        if discord.utils.get(member.roles, name=tname):
            return tid, tname
    return None, None

class TradeView(discord.ui.View):
    def __init__(self, cog, your_player: discord.Member, their_player: discord.Member, team1_id, team2_id, team1_name, team2_name):
        super().__init__(timeout=86400) # 24 hour timeout
        self.cog = cog
        self.your_player = your_player
        self.their_player = their_player
        self.team1_id, self.team2_id = team1_id, team2_id
        self.team1_name, self.team2_name = team1_name, team2_name

    @discord.ui.button(label="Approve Trade", style=discord.ButtonStyle.success, custom_id="trade_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verify the person clicking is a manager for Team 2
        manager_tid, _ = get_manager_team(interaction.user, self.cog.bot.config.get("team_ids", {}))
        if manager_tid != self.team2_id:
            return await interaction.response.send_message(f"❌ Only a GM/AGM/Owner of **{self.team2_name}** can approve this.", ephemeral=True)

        rosters = load_rosters()
        
        # Swap DB entries
        rosters[str(self.your_player.id)] = self.team2_id
        rosters[str(self.their_player.id)] = self.team1_id
        save_rosters(rosters)

        # Swap Discord Roles
        guild = interaction.guild
        t1_role = discord.utils.get(guild.roles, name=self.team1_name)
        t2_role = discord.utils.get(guild.roles, name=self.team2_name)
        
        if t1_role and t2_role:
            await self.your_player.remove_roles(t1_role)
            await self.your_player.add_roles(t2_role)
            await self.their_player.remove_roles(t2_role)
            await self.their_player.add_roles(t1_role)

        # Disable buttons and update message
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"✅ **TRADE APPROVED!**\n**{self.your_player.display_name}** goes to {self.team2_name}\n**{self.their_player.display_name}** goes to {self.team1_name}", view=self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="trade_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        manager_tid, _ = get_manager_team(interaction.user, self.cog.bot.config.get("team_ids", {}))
        if manager_tid != self.team2_id:
            return await interaction.response.send_message("❌ Only the receiving team's management can decline.", ephemeral=True)
            
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"❌ **TRADE DECLINED** by {interaction.user.mention}.", view=self)


class RosterManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sign", description="[GM/AGM] Sign a player to your roster.")
    async def sign(self, interaction: discord.Interaction, player: discord.Member):
        team_id, team_name = get_manager_team(interaction.user, self.bot.config.get("team_ids", {}))
        if not team_id:
            return await interaction.response.send_message("❌ You must have the Owner, GM, or AGM role AND your Team's role to sign players.", ephemeral=True)

        signup_data = get_signup_data(player.id)
        if not signup_data:
            return await interaction.response.send_message(f"❌ {player.display_name} hasn't used `/signup` yet.", ephemeral=True)

        rosters = load_rosters()
        if str(player.id) in rosters:
            return await interaction.response.send_message(f"❌ {player.display_name} is already on a roster. They must be dropped or traded.", ephemeral=True)

        # Eligibility check from Sheet
        ea_id = signup_data['gamertag']
        sheet_rosters = utils.get_roster_data_from_sheet(self.bot.config)
        played_game = any(ea_id.lower() == sheet_name.lower() for sheet_name in sheet_rosters.get(team_id, {}).keys())
        
        if not played_game:
            return await interaction.response.send_message(f"❌ Cannot sign **{ea_id}**. They must play at least 1 game with your team first.", ephemeral=True)

        # Process Sign
        rosters[str(player.id)] = team_id
        save_rosters(rosters)
        
        role = discord.utils.get(interaction.guild.roles, name=team_name)
        if role: await player.add_roles(role)

        await interaction.response.send_message(f"✅ **{team_name}** has signed **{ea_id}** ({player.mention})!\n*Positions: {', '.join(signup_data['positions'])} | Avail: {signup_data['availability']}*")

    @app_commands.command(name="drop", description="[GM/AGM] Drop a player from your roster.")
    async def drop(self, interaction: discord.Interaction, player: discord.Member):
        team_id, team_name = get_manager_team(interaction.user, self.bot.config.get("team_ids", {}))
        if not team_id: return await interaction.response.send_message("❌ You lack management permissions.", ephemeral=True)

        rosters = load_rosters()
        if rosters.get(str(player.id)) != team_id:
            return await interaction.response.send_message(f"❌ {player.display_name} is not on your roster.", ephemeral=True)

        del rosters[str(player.id)]
        save_rosters(rosters)

        role = discord.utils.get(interaction.guild.roles, name=team_name)
        if role: await player.remove_roles(role)

        await interaction.response.send_message(f"🗑️ **{team_name}** has released **{player.display_name}** to free agency.")

    @app_commands.command(name="trade", description="[GM/AGM] Propose a 1-for-1 trade with another team.")
    async def trade(self, interaction: discord.Interaction, drop_player: discord.Member, receive_player: discord.Member):
        team1_id, team1_name = get_manager_team(interaction.user, self.bot.config.get("team_ids", {}))
        if not team1_id: return await interaction.response.send_message("❌ You lack management permissions.", ephemeral=True)

        rosters = load_rosters()
        
        # Verify drop_player is on Team 1
        if rosters.get(str(drop_player.id)) != team1_id:
            return await interaction.response.send_message(f"❌ {drop_player.display_name} is not on your roster.", ephemeral=True)

        # Verify receive_player is on another roster
        team2_id = rosters.get(str(receive_player.id))
        if not team2_id or team2_id == team1_id:
            return await interaction.response.send_message(f"❌ {receive_player.display_name} must be on a different team's roster.", ephemeral=True)

        team2_name = self.bot.config.get("team_ids", {}).get(team2_id, str(team2_id))

        view = TradeView(self, drop_player, receive_player, team1_id, team2_id, team1_name, team2_name)
        await interaction.response.send_message(
            f"🚨 **TRADE PROPOSAL** 🚨\n**{team1_name}** proposes a trade to **{team2_name}**:\n\n"
            f"📤 Sending: {drop_player.mention}\n"
            f"📥 Receiving: {receive_player.mention}\n\n"
            f"*Management from {team2_name} must approve below.*",
            view=view
        )

async def setup(bot):
    await bot.add_cog(RosterManager(bot))
