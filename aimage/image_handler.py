import io
import re
import random
import logging
import asyncio
import aiohttp
import discord
from typing import Coroutine, Optional, Union

from redbot.core import commands

from aimage.abc import MixinMeta
from aimage.apis.response import ImageResponse
from aimage.common.helpers import delete_button_after, send_response
from aimage.common.params import ImageGenParams
from aimage.views.image_actions import ImageActions

logger = logging.getLogger("red.bz_cogs.aimage")


class ImageHandler(MixinMeta):
    async def _execute_image_generation(self,
                                        context: Union[commands.Context, discord.Interaction],
                                        payload: dict = None,
                                        params: ImageGenParams = None,
                                        callback: Optional[Coroutine] = None):
        payload = payload or {}
        guild = context.guild
        channel = context.channel
        user = context.user if isinstance(context, discord.Interaction) else context.author
        assert guild and isinstance(channel, discord.TextChannel) and isinstance(user, discord.Member)

        if params and params.init_image or payload and payload.get("init_images", ""):
            generate_method = 'generate_img2img'
        else:
            generate_method = 'generate_image'

        try:
            self.generating[user.id] = True
            for _ in range(10):
                try:
                    api = await self.get_api_instance(context)
                    generate_func = getattr(api, generate_method)
                    response: ImageResponse = await generate_func(params, payload)
                except (RuntimeError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError):
                    await asyncio.sleep(5)
                else:
                    break
        except ValueError as error:
            return await send_response(context, content=f":warning: Invalid parameter: {error}", ephemeral=True)
        except aiohttp.ClientResponseError as error:
            logger.exception(f"Failed request in host {guild.id}")
            return await send_response(context, content=":warning: Timed out! Bad response from host!", ephemeral=True)
        except aiohttp.ClientConnectorError:
            logger.exception(f"Failed request in server {guild.id}")
            return await send_response(context, content=":warning: Timed out! Could not reach host!", ephemeral=True)
        except NotImplementedError:
            return await send_response(context, content=":warning: This method is not supported by the host!", ephemeral=True)
        except Exception:
            logger.exception(f"Failed request in server {guild.id}")
            return await send_response(context, content=":warning: Something went wrong!", ephemeral=True)
        finally:
            self.generating[user.id] = False

        if response.is_nsfw and not channel.is_nsfw():
            return await send_response(context, content=f"🔞 Blocked NSFW image.", allowed_mentions=discord.AllowedMentions.none())

        id = context.id if isinstance(context, discord.Interaction) else context.message.id
        file = discord.File(io.BytesIO(response.data or b''), filename=f"image_{id}.{response.extension}", spoiler=response.is_nsfw)
        maxsize = await self.config.guild(guild).max_img2img()
        view = ImageActions(self, response.info_string, response.payload, user, channel, maxsize)

        msg = await send_response(context, file=file, view=view)
        
        asyncio.create_task(delete_button_after(msg))
        asyncio.create_task(self._update_autocomplete_cache(context))
        if callback:
            asyncio.create_task(callback)

        imagescanner = self.bot.get_cog("ImageScanner")
        if imagescanner and response.extension == "png":
            if channel.id in imagescanner.scan_channels:
                imagescanner.image_cache[msg.id] = ({0: response.info_string}, {0: response.data})
                try:
                    await msg.add_reaction("🔎")
                except discord.NotFound:
                    pass
