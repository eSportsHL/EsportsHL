import discord
from discord.ext import commands
import subprocess

class Updater(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # The @commands.is_owner() decorator is CRITICAL. 
    # It ensures ONLY YOU can run this command.
    @commands.command(name="update")
    @commands.is_owner() 
    async def update_bot(self, ctx):
        await ctx.send("⏳ Pulling latest code from GitHub...")
        
        try:
            # This simulates typing 'git pull' into your Ubuntu terminal
            result = subprocess.run(
                ['git', 'pull'], 
                capture_output=True, 
                text=True, 
                check=True
            )
            
            # Sends the terminal output back to Discord so you can see what changed
            await ctx.send(f"✅ Code pulled successfully! PM2 should restart the bot now.\n```bash\n{result.stdout}\n```")
            
        except subprocess.CalledProcessError as e:
            # If git pull fails (e.g., merge conflict), it will tell you the error
            await ctx.send(f"❌ Error pulling from GitHub:\n```bash\n{e.stderr}\n```")

async def setup(bot):
    await bot.add_cog(Updater(bot))
