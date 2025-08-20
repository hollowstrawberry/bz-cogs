import asyncio
import io
import logging
from collections import defaultdict
from copy import copy
import math
import re
from typing import List, Union

import aiohttp
import discord
from rapidfuzz import fuzz
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red

from aimage.abc import CompositeMetaClass
from aimage.common.constants import (DEFAULT_BADWORDS_BLACKLIST,
                                     DEFAULT_NEGATIVE_PROMPT, API_Type)
from aimage.common.params import ImageGenParams
from aimage.image_handler import ImageHandler
from aimage.settings import Settings

logger = logging.getLogger("red.bz_cogs.aimage")


class AImage(Settings,
             ImageHandler,
             commands.Cog,
             metaclass=CompositeMetaClass):
    """ Generate AI images using a A1111 endpoint """

    def __init__(self, bot):
        super().__init__()
        self.bot: Red = bot
        self.config = Config.get_conf(self, identifier=75567113)

        default_guild = {
            "endpoint": None,
            "api_type": API_Type.AUTOMATIC1111.value,
            "nsfw": True,
            "nsfw_tuning": -0.025,
            "words_blacklist": DEFAULT_BADWORDS_BLACKLIST,
            "blacklist_regex": "",
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
            "cfg": 5,
            "sampling_steps": 24,
            "sampler": "Euler a",
            "checkpoint": None,
            "vae": None,
            "adetailer": False,
            "tiledvae": False,
            "width": 1024,
            "height": 1024,
            "max_img2img": 1536,
            "auth": None,
            "scheduler": "Automatic"
        }

        self.session = aiohttp.ClientSession()
        self.generating = defaultdict(lambda: False)
        self.autocomplete_cache = defaultdict(dict)

        self.config.register_guild(**default_guild)

    async def red_delete_data_for_user(self, **kwargs):
        return

    async def cog_unload(self):
        await self.session.close()

    async def object_autocomplete(self, interaction: discord.Interaction, current: str, choices: list) -> List[app_commands.Choice[str]]:

        if not choices:
            await self._update_autocomplete_cache(interaction)
            return []

        choices = self.filter_list(choices, current)

        return [
            app_commands.Choice(name=choice, value=choice)
            for choice in choices[:25]
        ]

    async def samplers_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = self.autocomplete_cache[interaction.guild_id].get("samplers") or []
        return await self.object_autocomplete(interaction, current, choices)

    async def loras_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = self.autocomplete_cache[interaction.guild_id].get("loras") or []

        if not choices:
            await self._update_autocomplete_cache(interaction)
            return []

        weight = "1"
        previous = ""
        if current:
            if m := re.search(r"^((?:<[^>]+>\s*)+)([^<>]+)$", current): # multiple loras
                current = m.group(2)
                previous = m.group(1) + " "
            if m := re.search(r"^([^:]+):([+-]?\d*\.?\d+)$", current): # lora weight
                current = m.group(1)
                weight = m.group(2)

        choices = self.filter_list(choices, current, True)
        choices = [f"{previous}<lora:{choice}:{weight}>" if len(f"{previous}<lora:{choice}:{weight}>") <= 100 else f"<lora:{choice}:{weight}>" for choice in choices]
        return [app_commands.Choice(name=choice, value=choice) for choice in choices][:25]

    async def style_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = self.autocomplete_cache[interaction.guild_id].get("styles") or []

        if current:
            current_styles = current.split(",")
            if any(part in current_styles for part in choices):
                new_choices = []
                for choice in choices:
                    choice_parts = choice.split(", ")
                    if any(part in current_styles for part in choice_parts):
                        continue
                    new_choices.append(current + ", " + choice)
            choices = new_choices

        return await self.object_autocomplete(interaction, current, choices)

    async def checkpoint_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = self.autocomplete_cache[interaction.guild_id].get("checkpoints") or []
        return await self.object_autocomplete(interaction, current, choices)

    async def vae_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = self.autocomplete_cache[interaction.guild_id].get("vaes") or []
        return await self.object_autocomplete(interaction, current, choices)

    @ staticmethod
    def filter_list(options: list, current: str, strict: bool = False):
        results = []

        ratios = [(item, fuzz.partial_ratio(current.lower(), item.lower())) for item in options]

        sorted_options = sorted(ratios, key=lambda x: x[1], reverse=True)

        for item, ratio in sorted_options:
            if strict and ratio < 75:
                continue
            results.append(item)

        return results

    _parameter_descriptions = {
        "prompt": "The prompt to generate an image from.",
        "negative_prompt": "Undesired terms go here.",
        "cfg": "Sets the intensity of the prompt, 5 is common.",
        "seed": "Random number that generates the image, -1 for random.",
        "checkpoint": "The main AI model used to generate the image.",
        "vae": "The VAE converts the final details of the image.",
        "lora": "Shortcut to insert LoRA into the prompt.",
        "subseed": "Random number that defines variations on a set seed.",
        "variation": "Also known as subseed strength, makes variations on a set seed.",
    }

    _parameter_autocompletes = {
        "lora": loras_autocomplete,
        "checkpoint": checkpoint_autocomplete,
        "vae": vae_autocomplete,
    }

    @ commands.command(name="txt2img")
    @ checks.bot_has_permissions(attach_files=True)
    @ checks.bot_in_a_guild()
    async def imagine(self, ctx: commands.Context, *, prompt: str):
        """
        Generate an image with Stable Diffusion

        **Arguments**
            - `prompt` a prompt to generate an image from
        """
        if not self.autocomplete_cache[ctx.guild.id]:
            asyncio.create_task(self._update_autocomplete_cache(ctx))

        params = ImageGenParams(prompt=prompt)
        await self.generate_image(ctx, params=params)

    

    @ app_commands.command(name="txt2img")
    @ app_commands.describe(resolution="The dimensions of the image.",
                            **_parameter_descriptions)
    @ app_commands.autocomplete(**_parameter_autocompletes)
    @ app_commands.checks.bot_has_permissions(attach_files=True)
    @ app_commands.choices(resolution=[
            app_commands.Choice(name="Square", value="1024x1024"),
            app_commands.Choice(name="Portrait", value="832x1216"),
            app_commands.Choice(name="Landscape", value="1216x832"),
        ])
    @ app_commands.guild_only()
    async def imagine_app(
        self,
        interaction: discord.Interaction,
        resolution: str,
        prompt: str,
        negative_prompt: str = None,
        checkpoint: str = None,
        lora: str = "",
        cfg: app_commands.Range[float, 2, 8] = None,
        seed: app_commands.Range[int, -1, None] = -1,
        subseed: app_commands.Range[int, -1, None] = -1,
        variation: app_commands.Range[float, 0.0, 0.5] = 0,
        vae: str = None,
    ):
        """
        Generate an image using Stable Diffusion.
        """
        await interaction.response.defer(thinking=True)

        ctx: commands.Context = await self.bot.get_context(interaction)  # noqa
        if not await self._can_run_command(ctx, "txt2img"):
            return await interaction.followup.send("You do not have permission to do this.", ephemeral=True)

        width, height = tuple(int(x) for x in resolution.split("x"))

        if "masterpiece" not in prompt and "best quality" not in prompt:
            prompt = "masterpiece, best quality, " + prompt

        params = ImageGenParams(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            cfg=cfg,
            seed=seed,
            checkpoint=checkpoint,
            vae=vae,
            lora=lora,
            subseed=subseed,
            subseed_strength=variation
        )

        await self.generate_image(interaction, params=params)

    @ app_commands.command(name="img2img")
    @ app_commands.describe(image="The input image.",
                            denoising="How much the image should change. Try around 0.6",
                            scale="Resizes the image up or down, 0.5 to 2.0.",
                            **_parameter_descriptions)
    @ app_commands.autocomplete(**_parameter_autocompletes)
    @ app_commands.checks.bot_has_permissions(attach_files=True)
    @ app_commands.guild_only()
    async def reimagine_app(
            self,
            interaction: discord.Interaction,
            image: discord.Attachment,
            denoising: app_commands.Range[float, 0, 1],
            prompt: str,
            negative_prompt: str = None,
            checkpoint: str = None,
            lora: str = "",
            scale: app_commands.Range[float, 0.5, 2.0] = 1,
            cfg: app_commands.Range[float, 2, 8] = None,
            seed: app_commands.Range[int, -1, None] = -1,
            subseed: app_commands.Range[int, -1, None] = -1,
            variation: app_commands.Range[float, 0.0, 0.5] = 0,
            vae: str = None,
    ):
        """
        Convert an image using Stable Diffusion.
        """
        await interaction.response.defer(thinking=True)

        ctx: commands.Context = await self.bot.get_context(interaction)  # noqa
        if not await self._can_run_command(ctx, "txt2img"):
            return await interaction.followup.send("You do not have permission to do this.", ephemeral=True)

        if not image.content_type.startswith("image/"):
            return await interaction.followup.send("The file you uploaded is not a valid image.", ephemeral=True)

        size = image.width*image.height*scale*scale
        maxsize = (await self.config.guild(ctx.guild).max_img2img())**2
        if size > maxsize:
            return await interaction.followup.send(
                f"Max img2img size is {int(maxsize**0.5)}² pixels. "
                f"Your image {'after resizing would be' if scale != 0 else 'is'} {int(size**0.5)}² pixels, which is too big.",
                ephemeral=True)
        
        params = ImageGenParams(
            prompt=prompt,
            negative_prompt=negative_prompt,
            cfg=cfg,
            seed=seed,
            checkpoint=checkpoint,
            vae=vae,
            lora=lora,
            # img2img
            height=image.height*scale,
            width=image.width*scale,
            init_image=await image.read(),
            denoising=denoising,
            subseed=subseed,
            subseed_strength=variation
        )

        await self.generate_img2img(interaction, params=params)

    async def _can_run_command(self, ctx: commands.Context, command_name: str) -> bool:
        prefix = await self.bot.get_prefix(ctx.message)
        prefix = prefix[0] if isinstance(prefix, list) else prefix
        fake_message = copy(ctx.message)
        fake_message.content = prefix + command_name
        command = ctx.bot.get_command(command_name)
        fake_context: commands.Context = await ctx.bot.get_context(fake_message)  # noqa
        try:
            can = await command.can_run(fake_context, check_all_parents=True, change_permission_state=False)
        except commands.CommandError:
            can = False
        return can

    async def get_api_instance(self, ctx: Union[commands.Context, discord.Interaction]):
        api_type = await self.config.guild(ctx.guild).api_type()
        if api_type == API_Type.AUTOMATIC1111.value:
            from aimage.apis.a1111 import A1111
            instance = A1111(self, ctx)
        elif api_type == API_Type.AIHorde.value:
            from aimage.apis.aihorde import AIHorde
            instance = AIHorde(self, ctx)
        await instance._init()
        return instance

    async def _update_autocomplete_cache(self, ctx: Union[commands.Context, discord.Interaction]):
        api = await self.get_api_instance(ctx)
        try:
            logger.debug(f"Ran a update to get possible autocomplete terms in server {ctx.guild.id}")
            await api.update_autocomplete_cache(self.autocomplete_cache)
        except NotImplementedError:
            logger.debug(f"Autocomplete terms is not supported by the api in server {ctx.guild.id}")
            pass
