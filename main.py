import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import utils

# ============================================================
# main.py
# Version: 5.2.0
# Changelog:
#   v5.2.0 - BUGFIX: sorted() added to cog loader. os.listdir()
#             returns filesystem order on Linux (inode-dependent),
#             which breaks the patch chain. sorted() guarantees
#             alphabetical order so image_engine loads before
#             leaderboard_engine, statslogger before statsreader,
#             team_logos before team_logo_overrides, and
#             draft before draftrestore every single boot.
#   v5.1.0 - Added branding banner and version changelog on boot.
#             Matches cog now runs blocking sheet calls in executor
#             to prevent Discord heartbeat timeouts.
# ============================================================

VERSION  = "5.2.0"
BOT_NAME = "Echelon League Bot"

BOOT_BANNER = f"""
╔══════════════════════════════════════════╗
║         {BOT_NAME}              ║
║         Version {VERSION}                    ║
╠══════════════════════════════════════════╣
║  v5.2.0  sorted() cog loader — patch   ║
║          chain now deterministic        ║
║  v5.1.0  Executor fix for sheet 429s   ║
║  v5.0.0  Master Restore — Core release ║
╚══════════════════════════════════════════╝
"""

# Load environment variables from the .env file
load_dotenv()

# Grabs the token whether you named it "TOKEN" or "DISCORD_TOKEN" in your .env file
TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")

class HockeyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = utils.load_config()

    async def setup_hook(self):
        """This runs right before the bot connects to Discord. We load cogs here."""
        print(BOOT_BANNER)
        print(f"[LOG] 🚀 {BOT_NAME} v{VERSION} — Starting up... Loading Cogs.")

        # sorted() is CRITICAL — ensures deterministic patch chain on every boot:
        #   image_engine  (i) → leaderboard_engine (l)  [leaderboard patch wins]
        #   statslogger   (s) → statsreader         (s)  [reader overwrites base]
        #   team_logos    (t) → team_logo_overrides  (t)  [override patches resolver]
        #   draft         (d) → draftrestore         (d)  [restore imports draft]
        for filename in sorted(os.listdir('./cogs')):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"[LOG] ✅ [Loaded] {filename}")
                except Exception as e:
                    print(f"[LOG] ❌ [Failed to load] {filename}: {e}")

        try:
            synced = await self.tree.sync()
            print(f"[LOG] 🔄 [Synced] {len(synced)} slash commands.")
        except Exception as e:
            print(f"[LOG] ❌ [Sync Error] Failed to sync slash commands: {e}")

    async def on_ready(self):
        """This runs when the bot is fully connected and ready."""
        print(f"[LOG] ✅ Logged in as {self.user} (ID: {self.user.id})")
        print(f"[LOG] --- {BOT_NAME} v{VERSION} is ONLINE ---")
        await utils.send_log(self, f"✅ **{self.user.name} is now ONLINE** — {BOT_NAME} v{VERSION}")

bot = HockeyBot()

if __name__ == "__main__":
    if not TOKEN:
        print("⚠️ ERROR: Could not find your Discord Token in the .env file!")
        print("Make sure your .env file has a line like: TOKEN=your_actual_token_here")
    else:
        bot.run(TOKEN)
