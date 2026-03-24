# clear_commands.py (Corrected Version)
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1462962881183092950

# Use commands.Bot, which is compatible with your installed library
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} to clear commands...")
    
    guild_obj = discord.Object(id=GUILD_ID)

    # Clear commands for your specific guild
    print(f"Clearing commands for guild: {guild_obj.id}")
    bot.tree.clear_commands(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)
    print("Guild commands cleared.")

    # This part clears global commands, just in case
    print("Clearing global commands...")
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print("Global commands cleared.")
    
    print("Done. You can now close this script (CTRL+C).")
    await bot.close()

bot.run(BOT_TOKEN)

