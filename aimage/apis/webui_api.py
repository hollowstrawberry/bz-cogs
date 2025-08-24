import json
import base64
import logging
from enum import Enum
from typing import Any, Dict, Optional, Union

import discord
from redbot.core import commands
from tenacity import retry, stop_after_attempt, wait_random

from aimage.abc import MixinMeta
from aimage.apis.base_api import BaseAPI
from aimage.apis.response import ImageResponse
from aimage.common.constants import ADETAILER_ARGS, TILED_VAE_ARGS
from aimage.common.helpers import get_auth
from aimage.common.params import ImageGenParams

logger = logging.getLogger("red.bz_cogs.aimage")

cache_mapping = {
    "upscalers": "upscalers",
    "scripts": "scripts",
    "loras": "loras",
    "sd-models": "checkpoints",
    "sd-vae": "vaes",
    "samplers": "samplers",
    "prompt-styles": "styles",
    "schedulers": "schedulers",
}

A1111_SAMPLERS = [
    "DPM++ 2M",
    "DPM++ SDE",
    "DPM++ 2M SDE",
    "DPM++ 2M SDE Heun",
    "DPM++ 2S a",
    "DPM++ 3M SDE",
    "Euler a",
    "Euler",
    "LMS",
    "Heun",
    "DPM2",
    "DPM2 a",
    "DPM fast",
    "DPM adaptive",
    "Restart",
    "DDIM",
    "DDIM CFG++",
    "PLMS",
    "UniPC",
    "LCM",
    "DDPM"
]


class ImageGenerationType(Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"


class WebuiAPI(BaseAPI):
    def __init__(self, cog: MixinMeta, context: Union[commands.Context, discord.Interaction]):
        self.session = cog.session
        self.config = cog.config
        self.context = context
        self.guild = context.guild
        assert self.guild
        cog.autocomplete_cache[self.guild.id]["samplers"] = A1111_SAMPLERS

    async def _init(self):
        assert self.guild
        self.endpoint = await self.config.guild(self.guild).endpoint()
        self.auth = get_auth(await self.config.guild(self.guild).auth())

    async def update_autocomplete_cache(self, cache):
        assert self.guild
        for page, cache_key in cache_mapping.items():
            try:
                data = await self._get_terms(page)
            except Exception as e:
                logger.warning(f"Failed to update autocomplete cache for {cache_key} in {self.guild.id}: \n {e}")
                continue

            if page == "scripts":
                choices = [choice for choice in data["txt2img"]] if data else []
            elif page == "loras":
                choices = [choice['name'] for choice in data] if data else []
            elif page in ["sd-models", "sd-vae"]:
                choices = [choice["model_name"] for choice in data] if data else []
            else:
                choices = [choice["name"] for choice in data] if data else []

            cache[self.guild.id][cache_key] = choices

    async def generate_image(self, params: Optional[ImageGenParams] = None, payload: Optional[dict] = None):
        if params is None and payload is None:
            raise ValueError("Can't generate image with no payload and no params")
        payload = payload or await self._generate_payload(params)
        gen_type = ImageGenerationType.IMG2IMG if payload.get("init_images", []) else ImageGenerationType.TXT2IMG
        return await self._post_image_gen(payload, gen_type)

    async def _generate_payload(self, params: Optional[ImageGenParams]) -> dict:
        assert self.guild
        if params is None:
            return {}
        if params.negative_prompt is None:
            params.negative_prompt = ""
        stock_negative_prompt = await self.config.guild(self.guild).negative_prompt()
        if stock_negative_prompt not in params.negative_prompt:
            if params.negative_prompt:
                params.negative_prompt = f"{stock_negative_prompt}, {params.negative_prompt}"
            else:
                params.negative_prompt = stock_negative_prompt

        if "masterpiece" not in params.prompt and "best quality" not in params.prompt:
            params.prompt = "masterpiece, best quality, " + params.prompt

        payload: Dict[str, Any] = {
            "prompt": f"{params.prompt} {params.lora}",
            "negative_prompt": params.negative_prompt,
            "styles": params.style.split(", ") if params.style else [],
            "cfg_scale": params.cfg or await self.config.guild(self.guild).cfg(),
            "steps": params.steps or await self.config.guild(self.guild).sampling_steps(),
            "seed": params.seed,
            "subseed": params.subseed,
            "subseed_strength": params.subseed_strength,
            "sampler_name": params.sampler or await self.config.guild(self.guild).sampler(),
            "scheduler": params.scheduler or await self.config.guild(self.guild).scheduler(),
            "override_settings": {
                "sd_model_checkpoint": params.checkpoint or await self.config.guild(self.guild).checkpoint(),
                "sd_vae": params.vae or await self.config.guild(self.guild).vae()
            },
            "width": params.width or await self.config.guild(self.guild).width(),
            "height": params.height or await self.config.guild(self.guild).height(),
            "alwayson_scripts": {}
        }

        # force flux support for now
        if "flux" in payload["override_settings"]["sd_model_checkpoint"]:
            logger.debug("Flux model detected, setting scheduler to Simple and cfg_scale to 1")
            payload["scheduler"] = "Simple"
            payload["cfg_scale"] = 1

        if params.init_image:
            payload.update({
                "init_images": [base64.b64encode(params.init_image).decode("utf8")],
                "denoising_strength": params.denoising
            })

        if await self.config.guild(self.guild).adetailer():
            payload["alwayson_scripts"].update(ADETAILER_ARGS)

        if await self.config.guild(self.guild).tiledvae():
            payload["alwayson_scripts"].update(TILED_VAE_ARGS)

        nsfw = await self.config.guild(self.guild).nsfw()
        tuning = await self.config.guild(self.guild).nsfw_tuning()
        payload["script_name"] = "CensorScript"
        payload["script_args"] = [True, not nsfw, tuning]

        return payload

    @retry(wait=wait_random(min=3, max=5), stop=stop_after_attempt(3), reraise=True)
    async def _post_image_gen(self, payload, generation_type: ImageGenerationType):
        url = self.endpoint + generation_type.value
        async with self.session.post(url=url, json=payload, auth=self.auth) as response:
            r = await response.json()
            if response.status == 422:
                raise ValueError(r["detail"])
            elif response.status != 200:
                response.raise_for_status()
            data = base64.b64decode(r["images"][0])

            # a1111 shenanigans
            info = json.loads(r["info"])
            info_string = info.get("infotexts")[0]
            try:
                is_nsfw = info.get("extra_generation_params", {}).get("nsfw", [])[0]
            except IndexError:
                is_nsfw = False

            if logger.isEnabledFor(logging.DEBUG):
                del r["images"]
                logger.debug(f"Requested with parameters: {json.dumps(r, indent=4)}")

        return ImageResponse(data=data, info_string=info_string, is_nsfw=is_nsfw, payload=payload)

    @retry(wait=wait_random(min=3, max=5), stop=stop_after_attempt(1), reraise=True)
    async def _get_terms(self, page):
        url = self.endpoint + page
        async with self.session.get(url=url, auth=self.auth, raise_for_status=True) as response:
            return await response.json()
