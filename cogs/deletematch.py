# ============================================================
#  Echelon League Bot — deletematch.py
#  Version: 1.0.0
#  NEW COG — Never modifies utils.py or any existing cog.
#
#  Provides /deletematch <match_id> — removes all rows for a
#  given match ID from Player Stats and cleans up any merge
#  records involving that ID.
#
#  Changelog:
#    v1.0.0 — Initial release.
# ============================================================

VERSION  = "1.0.0"
COG_NAME = "DeleteMatch"

print(f"📦 [{COG_NAME}] Cog v{VERSION} loading — /deletematch command")

import utils
import discord
from discord.ext import commands
from discord import app_commands

class DeleteMatch(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        print(f"✅ [{COG_NAME}] v{VERSION} initialized")

    @app_commands.command(
        name="deletematch",
        description="[Admin] Delete all stats rows for a specific match ID from Player Stats."
    )
    @app_commands.describe(match_id="The Match ID to delete (e.g. 14690036030101)")
    @app_commands.checks.has_permissions(administrator=True)
    async def deletematch(self, interaction: discord.Interaction, match_id: str):
        await interaction.response.defer(ephemeral=True)

        match_id = match_id.strip()

        sh = utils.get_sheet()
        if not sh:
            return await interaction.followup.send("❌ Could not connect to Google Sheets.", ephemeral=True)

        try:
            ws   = sh.worksheet("Player Stats")
            rows = ws.get_all_values()
        except Exception as e:
            return await interaction.followup.send(f"❌ Sheet error: `{e}`", ephemeral=True)

        # Find all rows matching this match ID (col 0)
        to_delete = []
        for i, row in enumerate(rows, start=1):
            if row and str(row[0]).strip() == match_id:
                to_delete.append(i)

        if not to_delete:
            return await interaction.followup.send(
                f"⚠️ No rows found for Match ID `{match_id}` in Player Stats.",
                ephemeral=True
            )

        # Delete in reverse order to preserve row indices
        for row_idx in reversed(to_delete):
            ws.delete_rows(row_idx)

        # Also clean up any merge record involving this ID
        merge_cleaned = False
        try:
            from cogs.lagout import _do_unmerge, get_merge_map
            merge_map = get_merge_map(sh)
            # If this was a primary ID, unmerge it
            if match_id in [r for r in merge_map.values()]:
                _do_unmerge(sh, match_id)
                merge_cleaned = True
            # If it was an absorbed ID, unmerge the primary
            elif match_id in merge_map:
                primary = merge_map[match_id]
                _do_unmerge(sh, primary)
                merge_cleaned = True
        except Exception:
            pass

        await utils.send_log(
            self.bot,
            f"🗑️ Match `{match_id}` deleted by {interaction.user} — {len(to_delete)} rows removed."
        )

        await interaction.followup.send(
            f"✅ Deleted **{len(to_delete)} rows** for Match ID `{match_id}`.\n"
            + (f"🔀 Merge record also cleaned up.\n" if merge_cleaned else "")
            + f"\nRun `/updateresults` to refresh standings and season image.",
            ephemeral=True
        )

    @deletematch.error
    async def _error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(DeleteMatch(bot))
    print(f"✅ [{COG_NAME}] setup() complete — v{VERSION}")
