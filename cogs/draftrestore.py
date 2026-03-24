# draft_restore.py
# Version: 1.0.0
# Purpose: Re-registers the DraftBoardView persistent view on bot startup
# so buttons/selects on existing draft board messages survive restarts.

import discord
from discord.ext import commands
from cogs.draft import DraftBoardView, get_free_agents

VERSION = "1.0.0"

class DraftRestore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print(f"📋 [DraftRestore v{VERSION}] Cog loaded.")

    @commands.Cog.listener()
    async def on_ready(self):
        # Re-register the persistent DraftBoardView so existing board messages
        # remain interactive after a bot restart.
        try:
            fa = get_free_agents()
            self.bot.add_view(DraftBoardView(fa))
            print(f"✅ [DraftRestore v{VERSION}] DraftBoardView re-registered — draft board is live.")
            await self._log_restore()
        except Exception as e:
            print(f"❌ [DraftRestore v{VERSION}] Failed to restore DraftBoardView: {e}")

    async def _log_restore(self):
        import utils
        await utils.send_log(self.bot, f"📋 **Draft Board View Restored** (DraftRestore v{VERSION}) — buttons are active.")

async def setup(bot):
    await bot.add_cog(DraftRestore(bot))
