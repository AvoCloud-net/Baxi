import discord
import asyncio
from discord.ext import tasks, commands
from reds_simple_logger import Logger
from assets.share import globalchat_message_data
import assets.data as datasys
import copy

logger = Logger()


class SyncGlobalchatMessageDataTask:
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
            save_globalchat_message_data(), name="save_globalchat_message_data"
        )

        if success:
            if response == "ncds":
                logger.debug.info("[GCMD] No change in data detected")
            else:
                logger.debug.success("[GCMD] Data synced with data-structure")
                self.old_data = copy.deepcopy(globalchat_message_data)
        else:
            logger.error(f"[GCMD] Sync failed: {response}")
