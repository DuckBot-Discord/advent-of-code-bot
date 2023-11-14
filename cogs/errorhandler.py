from logging import getLogger
from discord.ext import commands

_log = getLogger('command errors')


class ErrorHandler(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
            return
        _log.error(f'Exception in command %s', ctx.command, exc_info=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorHandler(bot))
