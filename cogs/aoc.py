from __future__ import annotations

from datetime import datetime, time, timezone

import re
import asyncpg
import discord
from logging import getLogger
from discord import app_commands
from discord.ext import commands, tasks

from bot import AOCBot, get
from .models import Leaderboard

_log = getLogger(__name__)


def get_times() -> list[time]:
    times = [time(hour=0, minute=m, tzinfo=timezone.utc) for m in range(0, 60, 10)]
    for i in range(1, 24):
        times += [time(hour=i, minute=m, tzinfo=timezone.utc) for m in range(0, 60, 15)]
    return times


class AOC(commands.Cog):
    def __init__(self, bot: AOCBot) -> None:
        super().__init__()
        self.bot = bot
        self.leaderboard: Leaderboard = {'members': {}, 'owner_id': 0, 'event': 'unknown'}

    @property
    def guild(self) -> discord.Guild:
        """Duck Hideout"""
        guild = self.bot.get_guild(int(get('GUILD_ID')))
        if not guild:
            raise RuntimeError("Could not find the specified guild")
        return guild

    @property
    def role(self) -> discord.Role:
        """Duck Hideout"""
        role = self.guild.get_role(int(get('AOC_ROLE_ID')))
        if not role:
            raise RuntimeError("Could not find the AOC role")
        return role

    async def update_leaderboard(self) -> Leaderboard:
        _log.info("Updating leaderboard...")

        try:
            url = f"https://adventofcode.com/{datetime.now().year}/leaderboard/private/view/{get('LEADERBOARD_ID')}.json"
            cookies = {'session': get('AOC_SESSION')}

            resp = await self.bot.session.get(url, cookies=cookies)
            resp.raise_for_status()

            self.leaderboard: Leaderboard = await resp.json()
            _log.info("Successfully updated leaderboard.")

        except Exception as e:
            _log.error("Failed to update leaderboard.", exc_info=e)

        return self.leaderboard

    async def cog_load(self) -> None:
        """Starts the process of fetching the leaderboard."""
        self.update_leaderboard_and_names.start()
        self.daily_thread.start()

    async def cog_unload(self) -> None:
        self.update_leaderboard_and_names.cancel()
        self.daily_thread.cancel()

    @tasks.loop(time=get_times())
    async def update_leaderboard_and_names(self):
        await self.update_leaderboard()
        await self.update_all_names()

    @tasks.loop(time=time(hour=5))
    async def daily_thread(self):
        now = discord.utils.utcnow()
        if now.month != 12:
            return

        forum = self.bot.get_channel(1179942162511708220)

        if not isinstance(forum, discord.ForumChannel):
            return
        if discord.utils.find(lambda t: f'{now.year}: Day {now.day}:' in t.name, forum.threads):
            return

        async with self.bot.session.get(f'https://adventofcode.com/{now.year}/day/{now.day}') as res:
            res.raise_for_status()
            body = await res.text()
            title = re.findall(r"--- Day \d+: (.+) ---", body)[0]
            title = f"--- {now.year}: Day {now.day}: {title} ---"

            if discord.utils.get(forum.threads, name=title):
                return

            await forum.create_thread(
                name=title,
                content=f"{self.role.mention} {str(res.url)}\n-# Don't want notifications? `/unlink` to remove your role!",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

    @update_leaderboard_and_names.error
    async def error_log(self, error: BaseException):
        _log.error("An unexpected exception happened within the cache task", exc_info=error)
        self.update_leaderboard_and_names.restart()

    @daily_thread.before_loop
    @update_leaderboard_and_names.before_loop
    async def ct_before_loop(self):
        await self.bot.wait_until_ready()

    def trim_name(self, member: discord.Member) -> str:
        """Returns the member's name without the star counter."""
        match = re.fullmatch(r'^(.+)⭐\s*(?:[0-9]+|\?)$', member.display_name)
        if match:
            return match.group(1).strip()
        return member.display_name

    async def update_all_names(self, bypass: bool = False):
        """Updates all the nicks of users who have a claimed aoc user."""
        if bypass or datetime.now().month == 12:
            await self.guild.chunk()
            for member in self.guild.members:
                await self.update_name(member)

    async def clear_names(self):
        """Clears all the names of the star counters."""
        await self.guild.chunk()
        for member in self.guild.members:
            name = self.trim_name(member)
            if name != member.display_name:
                try:
                    await member.edit(nick=name != member.name and name or None)
                except:
                    pass

    async def update_name(self, member: discord.Member) -> None:
        """Updates a single member's name"""
        try:
            guild = member.guild
            name = self.trim_name(member)
            if member == guild.owner or member.top_role >= guild.me.top_role:
                return
            uid = await self.bot.pool.fetchval("SELECT aoc_user_id FROM linked_accounts WHERE user_id = $1", member.id)
            if not uid:
                kwargs = {}
                if member.display_name != name:
                    kwargs.update(nick=name)

                if self.role in member.roles:
                    kwargs.update(roles=[r for r in member.roles if r != self.role])

                if kwargs:
                    await member.edit(**kwargs)

                return

            stars = self.leaderboard.get("members", {}).get(str(uid), {}).get("stars") or 0
            new = f"{name} ⭐{stars}"
            kwargs = {}

            if stars and member.display_name != new:
                kwargs.update(nick=new)

            if self.role not in member.roles:
                kwargs.update(roles=member.roles + [self.role])

            if kwargs:
                await member.edit(**kwargs)
        except discord.HTTPException:
            pass

    @app_commands.command(name='link')
    @app_commands.describe(user_id='Your AOC user ID. Run /link for how to get it.')
    async def link(self, interaction: discord.Interaction, user_id: int | None):
        """Links your AOC account to your Discord account."""
        if not user_id:
            text = (
                "**How to get your AOC User ID:**"
                "\nFirst head to [adventofcode.com](https://adventofcode.com/) and log in, Click on `[Settings]`, there you will see your User ID:"
                "\n\n```\n\u200b"
                "\nWhat would you like to be called?"
                "\n"
                "\n( ) (anonymous user #1234567)"
                "\n        There it is! ^^^^^^^"
                "\n\u200b\n```"
                f"\nGreat! Now you can claim your account using `/link user_id: YOUR ID`"
            )
            return await interaction.response.send_message(text, ephemeral=True)
        try:
            await self.bot.pool.execute("INSERT INTO linked_accounts VALUES ($1, $2)", interaction.user.id, user_id)
        except asyncpg.UniqueViolationError as error:
            if error.constraint_name == "linked_accounts_pkey":
                detail = "You already have an AOC User ID claimed. Please `/unlink` first!"
            else:
                detail = "That AOC User ID is already claimed."
            await interaction.response.send_message(detail, ephemeral=True)
        else:
            await interaction.response.send_message(
                f'Succesfully linked AOC account. Please go [here](https://adventofcode.com/leaderboard/private) and join the leaderboard (`{get("LEADERBOARD_INVITE")}`) so we can track your stars.'
            )
            if isinstance(interaction.user, discord.Member):
                await self.update_name(interaction.user)

    @app_commands.command(name='unlink')
    async def unlink(self, interaction: discord.Interaction):
        """Unlinks the AOC user ID from your account"""
        data = await self.bot.pool.fetchrow(
            "DELETE FROM linked_accounts WHERE user_id = $1 RETURNING *", interaction.user.id
        )
        if not data:
            return await interaction.response.send_message(
                'You do not have an AOC account linked to your account.', ephemeral=True
            )
        await interaction.response.send_message('Account unlinked.')

        if isinstance(interaction.user, discord.Member):
            member: discord.Member | None = interaction.user
        else:
            member = self.guild.get_member(interaction.user.id)
        if member:
            await self.update_name(member)

    @app_commands.command(name='leaderboard')
    async def display_leaderboard(self, interaction: discord.Interaction):
        """Displays this server's AOC leaderboard"""
        await interaction.response.defer()

        await self.update_leaderboard()
        leaderboard_data = sorted(
            list(self.leaderboard["members"].values()),
            key=lambda u: (u["local_score"], u["name"]),
            reverse=True,
        )

        user_mapping = {
            entry["aoc_user_id"]: entry["user_id"]
            for entry in await self.bot.pool.fetch("SELECT aoc_user_id, user_id FROM linked_accounts")
        }

        paginator = commands.Paginator(prefix="", suffix="")
        score_width = len(str(max([x["local_score"] for x in leaderboard_data])))
        index_width = len(str(len(leaderboard_data))) + 1

        previous_score = 0
        for idx, leaderboard_entry in enumerate(leaderboard_data, start=1):

            name = leaderboard_entry["name"]
            discord_id = user_mapping.get(leaderboard_entry["id"], None)
            if discord_id:
                discord_user = self.guild.get_member(discord_id)
                if discord_user:
                    name = discord_user.mention

            if leaderboard_entry["local_score"] == previous_score:
                index = "".rjust(index_width)

            else:
                index = f"{idx})".rjust(index_width)
            previous_score = leaderboard_entry["local_score"]

            score = str(leaderboard_entry['local_score']).rjust(score_width)

            paginator.add_line(f"`{index} {score}` {name}")

        pages = iter(paginator.pages)
        await interaction.followup.send(next(pages))

        for page in pages:
            if isinstance(interaction.channel, discord.abc.Messageable):
                await interaction.channel.send(page)
            else:
                await interaction.followup.send(page)


async def setup(bot: AOCBot):
    await bot.add_cog(AOC(bot))
