import asyncio
from abc import ABC
from typing import Coroutine, Optional, Union, List, Dict
from aiohttp import ClientSession

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from aimage.schema import ImageGenParams, QueuedImageGen


class CompositeMetaClass(type(commands.Cog), type(ABC)):
    pass


class MixinMeta(ABC):
    bot: Red
    config: Config
    session: ClientSession
    autocomplete_cache: dict
    queued_images: Dict[str, QueuedImageGen]
    queue_task: discord.Optional[asyncio.Task]
    endpoint: str

    def __init__(self, *args):
        pass

    async def generate_image(self,
                             context: Union[commands.Context, discord.Interaction],
                             payload: dict = None,
                             params: ImageGenParams = None,
                             callback: Optional[Coroutine] = None,
                             message_content: Optional[str] = None
                             ) -> None:
        raise NotImplementedError

    async def request_image(self,
                            context: Union[commands.Context, discord.Interaction],
                            params: Optional[ImageGenParams],
                            payload: Optional[dict]
                            ) -> dict:
        raise NotImplementedError

    async def update_autocomplete_cache(self, *args, **kwargs):
        raise NotImplementedError
