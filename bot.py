from __future__ import annotations
import os
import dotenv
import asyncio
import aiohttp
import discord
import asyncpg
import traceback
from datetime import time, datetime, timezone
from logging import getLogger
from typing import TYPE_CHECKING
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from cogs.aoc import AOC

log = getLogger('bot')

INITIAL_EXTENSIONS = ['cogs.errorhandler', 'jishaku'] + (['cogs.aoc'] if datetime.now().month == 12 else [])


def get(k: str) -> str:
    v = os.getenv(k)
    if not v:
        raise RuntimeError("'%s' not set in the .env file!" % k)
    return v


class AOCBot(commands.Bot):
    """The Advent Of Code Bot for the Duck Hideout guild"""

    def __init__(self, pool: asyncpg.Pool, session: aiohttp.ClientSession) -> None:
        status = discord.Status.online if datetime.now().month == 12 else discord.Status.offline
        super().__init__(
            intents=discord.Intents(guilds=True, members=True, messages=True),
            command_prefix=commands.when_mentioned,
            status=status,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.listening, name='/link'),
        )
        self.pool: asyncpg.Pool[asyncpg.Record] = pool
        self.session: aiohttp.ClientSession = session

    async def setup_hook(self) -> None:
        """|coro| A coroutine called by the library between .login() and .connect()"""
        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.info('Loaded extension %s', extension)
            except:
                log.error("Failed to load %s:\n%s", extension, traceback.format_exc())

    @tasks.loop(time=time(hour=0, tzinfo=timezone.utc))
    async def check_for_times(self):
        if datetime.now().month == 12:
            if 'cogs.aoc' not in self.extensions.keys():
                await self.load_extension('cogs.aoc')
                await self.tree.sync()

            if self.status == discord.Status.offline:
                self.status = discord.Status.offline
                await self.change_presence(status=discord.Status.online)
        else:
            if 'cogs.aoc' in self.extensions.keys():
                cog: AOC = self.get_cog('AOC')  # type: ignore
                if cog:
                    await cog.clear_names()
                await self.unload_extension('cogs.aoc')
                await self.tree.sync()

            if self.status == discord.Status.online:
                self.status = discord.Status.offline
                await self.change_presence(status=discord.Status.offline)

    @check_for_times.before_loop
    async def ctf_before(self):
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        """|coro| Called when the bot's internal cache is ready."""
        log.info("Logged in as %s", str(self.user))

    async def on_error(self, event_method: str, /, *args, **kwargs) -> None:
        log.error("Error in event '%s'\n%s", event_method, traceback.format_exc())


if __name__ == "__main__":
    dotenv.load_dotenv()

    async def startup():
        async with asyncpg.create_pool(get("DSN")) as pool, aiohttp.ClientSession() as session, AOCBot(pool, session) as bot:
            discord.utils.setup_logging()
            await bot.start(token=get("TOKEN"))

    asyncio.run(startup())
