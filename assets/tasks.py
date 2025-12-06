import asyncio
from discord.ext import tasks, commands

from reds_simple_logger import Logger
from assets.share import globalchat_message_data
import assets.data as datasys
import copy

logger = Logger()


class GCDH_Task:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.old_data: dict = {}

    @tasks.loop(seconds=15)
    async def sync_globalchat_message_data(self):
        async def save_globalchat_message_data():
            if self.old_data == globalchat_message_data:
                return "ncds", True
            else:
                try:
                    datasys.save_data(
                        1001, "globalchat_message_data", globalchat_message_data
                    )
                    return "Success", True
                except Exception as e:
                    return f"{e}", False

        response, success = await asyncio.create_task(
            save_globalchat_message_data(), name="GCDH"
        )

        if success:
            if response == "ncds":
                logger.debug.info("[GCDH] No change in data detected")
            else:
                logger.debug.success("[GCDH] Data synced with data-structure")
                self.old_data = copy.deepcopy(globalchat_message_data)
        else:
            logger.error(f"[GCDH] Sync failed: {response}")


class UpdateStatsTask:
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot

    @tasks.loop(minutes=10)
    async def update_stats(self):
        guild_count = len(self.bot.guilds)
        
        unique_user_ids = set()
        for guild in self.bot.guilds:
            for member in guild.members:
                if not member.bot: 
                    unique_user_ids.add(member.id)
        
        user_count = len(unique_user_ids)

        stats: dict = dict(datasys.load_data(1001, "stats"))
        stats["guild_count"] = guild_count
        stats["user_count"] = user_count
        top_servers: dict = {server.name: server.member_count for server in self.bot.guilds}
        stats["top_servers"] = dict(
            sorted(
                top_servers.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        )
        datasys.save_data(1001, "stats", stats)


        logger.debug.info(
            f"[Stats] Updated stats: Guilds: {guild_count}, Unique Users: {user_count}"
        )