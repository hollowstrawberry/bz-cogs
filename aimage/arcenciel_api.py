import io
import re
import logging
from typing import List, Union

import discord
from redbot.core import commands

from aimage.abc import MixinMeta
from aimage.constants import ADETAILER_ARGS
from aimage.schema import ImageGenParams
from aimage.helpers import clean_model_prefix, is_nsfw

logger = logging.getLogger("red.holo-cogs.aimage")


class ArcEnCielAPI(MixinMeta):

    async def update_autocomplete_cache(self) -> None:
        url = self.endpoint + "/generator/options"
        async with self.session.get(url=url) as response:
            data = await response.json()
            for key, model_names in data["models"].items():
                self.autocomplete_cache[key] = [(name, clean_model_prefix(name)) for name in model_names]
            for key in ["samplers", "schedulers"]:
                self.autocomplete_cache[key] = data["limits"][key]
        # this endpoint returns loras while the other doesn't
        url = self.endpoint + "/generator/models"
        async with self.session.get(url=url) as response:
            data = await response.json()
            for key, models in data.items():
                self.autocomplete_cache[key] = [(model["name"], model["displayName"]) for model in models]
            

    async def request_image(self,
                          context: Union[commands.Context, discord.Interaction],
                          params: ImageGenParams = None,
                          payload: dict = None,
                          ) -> dict:
        assert params or payload
        member = context.user if isinstance(context, discord.Interaction) else context.author
        assert isinstance(context.channel, discord.abc.MessageableChannel) and isinstance(member, discord.Member)
        nsfw = is_nsfw(context.channel)
        payload = payload or await self.build_imagegen_payload(params, member, nsfw)  # type: ignore
        url = self.endpoint + "/generator/jobs"
        async with self.session.post(url=url, json=payload) as response:
            r = await response.json()
        return r["job"]
    
    async def fetch_queue(self) -> List[dict]:
        url = self.endpoint + "/generator/jobs"
        async with self.session.get(url=url) as response:
            r = await response.json()
        return r["jobs"]
    
    async def download_image(self, id: int, outputId: int) -> io.BytesIO:
        url = f"{self.endpoint}/api/generator/jobs/{id}/outputs/{outputId}/download"
        async with self.session.get(url=url) as response:
            b = await response.read()
        return io.BytesIO(b)
    
    async def build_imagegen_payload(self, params: ImageGenParams, member: discord.Member, nsfw: bool) -> dict:
        if params.negative_prompt is None:
            params.negative_prompt = ""
            stock_negative_prompt = await self.config.negative_prompt()
            if stock_negative_prompt not in params.negative_prompt:
                if params.negative_prompt:
                    params.negative_prompt = f"{stock_negative_prompt}, {params.negative_prompt}"
                else:
                    params.negative_prompt = stock_negative_prompt

        if "masterpiece" not in params.prompt and "best quality" not in params.prompt:
            params.prompt = "masterpiece, best quality, " + params.prompt
            loras = []
            for lora in re.findall(r"(<lora:([^:]+):(\d+\.?\d*)>)", params.prompt + params.lora):
                tag, name, weight = lora
                loras.append({
                    "name": name,
                    "weight": weight,
                })
                params.prompt = params.prompt.replace(tag, "")

        payload = {
            "mode": "txt2img",
            "prompt": params.prompt,
            "negativePrompt": params.negative_prompt or await self.config.negative_prompt(),
            "modelName": params.checkpoint or await self.config.member(member).checkpoint() or await self.config.checkpoint() or "",
            "vaeName": params.vae or await self.config.vae(),
            "seed": params.seed,
            "steps": params.steps or await self.config.sampling_steps(),
            "cfg": params.cfg or await self.config.cfg(),
            "samplerName": params.sampler or await self.config.sampler(),
            "scheduler": params.sampler or await self.config.sampler(),
            "width": params.width or await self.config.width(),
            "height": params.height or await self.config.height(),
            "batchSize": 1,
            "extraSeed": params.subseed,
            "extraSeedStrength": params.subseed_strength,
            "loras": loras,
            "sfwMode": nsfw,
        }
        if await self.config.adetailer():
            payload.update(ADETAILER_ARGS)

        return payload
