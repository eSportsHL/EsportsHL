import discord
from discord.ext import commands
import os
import sys

class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # This ensures only the Bot Owner (the person who made the bot in the portal) 
    # or someone with Administrator permissions can use these.
    async def cog_check(self, ctx):
        return ctx.author.guild_permissions.administrator

    @commands.command(name="reload")
    async def reload(self, ctx, *, cog: str):
        """Reloads a specific cog. Usage: !reload stats"""
        try:
            # We add 'cogs.' prefix because your main.py loads from that folder
            await self.bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"✅ Successfully reloaded `{cog}.py`")
        except Exception as e:
            await ctx.send(f"❌ Error reloading `{cog}`:\n```py\n{e}\n```")

    @commands.command(name="sync")
    async def sync(self, ctx):
        """Syncs slash commands to the Discord UI"""
        await ctx.send("🔄 Syncing slash commands... this can take a moment.")
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ Synced {len(synced)} slash commands to this server.")
        except Exception as e:
            await ctx.send(f"❌ Sync failed:\n```py\n{e}\n```")

    @commands.command(name="restart")
    async def restart(self, ctx):
        """Shuts down the bot process."""
        await ctx.send("👋 Shutting down... If you use a process manager, I'll be back in a second!")
        await self.bot.close()
        # This exits the python script
        sys.exit()

async def setup(bot):
    await bot.add_cog(Dev(bot))
