import datetime
import random

import openai
from discord.ext import tasks

from aiuser.abc import MixinMeta
from aiuser.model.openai import OpenAI_LLM_Response
from aiuser.prompts.random.base import RandomEventPrompt


class RandomMessageTask(MixinMeta):
    @tasks.loop(minutes=33)
    async def random_message_trigger(self):
        if not openai.api_key:
            return
        if not self.bot.is_ready():
            return
        for guild_id, channels in self.channels_whitelist.items():

            guild = self.bot.get_guild(guild_id)
            if not guild or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            if not await self.config.guild(guild).random_messages_enabled():
                continue
            if random.random() > await self.config.guild(guild).random_messages_percent():
                continue

            if not channels:
                continue

            channel = guild.get_channel(channels[random.randint(0, len(channels) - 1)])

            if not channel:
                continue

            last = await channel.fetch_message(channel.last_message_id)
            if last.author.id == guild.me.id:
                # skip spamming channel with random event messages
                continue

            last_created = last.created_at.replace(tzinfo=datetime.timezone.utc)

            if abs((datetime.datetime.now(datetime.timezone.utc) - last_created).total_seconds()) > 3600:
                # only sent to channels with 1 hour since last message
                continue

            ctx = await self.bot.get_context(last)

            if not await self.bot.ignored_channel_or_guild(ctx):
                continue

            random_prompt = await RandomEventPrompt(self, ctx.message).get_list()
            await OpenAI_LLM_Response(ctx, self.config, random_prompt).sent_response(standalone=True)
