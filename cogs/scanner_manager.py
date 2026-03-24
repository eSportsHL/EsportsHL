import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
import utils

class ScannerManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Default config if not present
        if "scan_schedule" not in self.bot.config:
            self.bot.config["scan_schedule"] = {
                "days": [0, 1, 2, 3, 4, 5, 6], # 0=Mon, 6=Sun
                "start_hour": 0,               # 24h format
                "end_hour": 23,
                "enabled": True
            }
        self.scheduler_loop.start()

    def cog_unload(self):
        self.scheduler_loop.cancel()

    @tasks.loop(minutes=1)
    async def scheduler_loop(self):
        """The 'Brain' that flips the switch on the Matches scraper."""
        now = datetime.now()
        current_day = now.weekday()
        current_hour = now.hour
        
        sched = self.bot.config["scan_schedule"]
        
        # Determine if we SHOULD be scanning right now
        should_scan = (
            sched["enabled"] and 
            current_day in sched["days"] and 
            sched["start_hour"] <= current_hour <= sched["end_hour"]
        )

        # Get the Matches Cog (the read-only one)
        matches_cog = self.bot.get_cog("Matches")
        if not matches_cog:
            return

        # Flip the switch
        is_running = matches_cog.match_check_loop.is_running()
        
        if should_scan and not is_running:
            matches_cog.match_check_loop.start()
            await utils.send_log(self.bot, "⏰ Schedule: **Starting** auto-scanner.")
        elif not should_scan and is_running:
            matches_cog.match_check_loop.stop()
            await utils.send_log(self.bot, "⏰ Schedule: **Stopping** auto-scanner (Outside active hours).")

    @app_commands.command(name="set_schedule", description="Set when the auto-scanner is allowed to run.")
    @app_commands.describe(
        start_hour="Hour to start (0-23)", 
        end_hour="Hour to stop (0-23)", 
        days="Days active (e.g., 0,1,2 for Mon-Wed or 'all')"
    )
    async def set_schedule(self, interaction: discord.Interaction, start_hour: int, end_hour: int, days: str = "all"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        # Parse days
        if days.lower() == "all":
            day_list = [0, 1, 2, 3, 4, 5, 6]
        else:
            try:
                day_list = [int(d.strip()) for d in days.split(",")]
            except:
                return await interaction.response.send_message("❌ Format days as numbers: 0,1,2 (0 is Monday).", ephemeral=True)

        self.bot.config["scan_schedule"].update({
            "days": day_list,
            "start_hour": start_hour,
            "end_hour": end_hour
        })
        utils.save_config(self.bot.config)
        
        await interaction.response.send_message(
            f"✅ **Schedule Updated!**\n"
            f"Running daily between **{start_hour}:00** and **{end_hour}:59** on days: {day_list}\n"
            f"*The switch will trigger within 60 seconds.*"
        )

    @app_commands.command(name="scanner_toggle", description="Manually enable/disable the auto-scanner entirely.")
    async def scanner_toggle(self, interaction: discord.Interaction, enabled: bool):
        self.bot.config["scan_schedule"]["enabled"] = enabled
        utils.save_config(self.bot.config)
        state = "ENABLED" if enabled else "DISABLED"
        await interaction.response.send_message(f"⚙️ Auto-scanner master switch set to: **{state}**")
    # --- ADD TO BOTTOM OF SCANNERMANAGER CLASS ---

    @app_commands.command(name="scanner_settings", description="Toggle which match types are auto-scanned.")
    @app_commands.describe(public="Scan public matches?", playoffs="Scan playoff matches?")
    async def scanner_settings(self, interaction: discord.Interaction, public: bool = None, playoffs: bool = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        sched = self.bot.config["scan_schedule"]
        
        # Only update if the user provided a value
        if public is not None:
            sched["scan_public"] = public
        if playoffs is not None:
            sched["scan_playoffs"] = playoffs

        utils.save_config(self.bot.config)
        
        status_pub = "ENABLED" if sched.get("scan_public") else "DISABLED"
        status_ply = "ENABLED" if sched.get("scan_playoffs") else "DISABLED"
        
        await interaction.response.send_message(
            f"✅ **Scanner Settings Updated!**\n"
            f"Public Matches: **{status_pub}**\n"
            f"Playoff Matches: **{status_ply}**"
        )
async def setup(bot):
    await bot.add_cog(ScannerManager(bot))
