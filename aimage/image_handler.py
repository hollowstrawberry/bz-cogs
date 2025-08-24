import io
import logging
import asyncio
import re
import aiohttp
import discord
from typing import Coroutine, Optional, Union

from redbot.core import commands

from aimage.abc import MixinMeta
from aimage.apis.response import ImageResponse
from aimage.common.helpers import delete_button_after, send_response
from aimage.common.params import ImageGenParams
from aimage.views.image_actions import ImageActions

log = logging.getLogger("red.bz_cogs.aimage")


class ImageHandler(MixinMeta):
    async def _execute_image_generation(self,
                                        context: Union[commands.Context, discord.Interaction],
                                        payload: dict = None,
                                        params: ImageGenParams = None,
                                        callback: Optional[Coroutine] = None,
                                        message_content: Optional[str] = None):
        payload = payload or {}
        guild = context.guild
        channel = context.channel
        user = context.user if isinstance(context, discord.Interaction) else context.author
        assert guild and isinstance(channel, discord.TextChannel) and isinstance(user, discord.Member)

        prompt = params.prompt if params else payload.get("prompt", "")
        try:
            log.info(f"Starting generation, {prompt=}")
            self.generating[user.id] = True
            for _ in range(10):
                try:
                    api = await self.get_api_instance(context)
                    response: ImageResponse = await api.generate_image(params, payload)
                except (RuntimeError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError):
                    log.info("Failed to generate, sleeping...")
                    await asyncio.sleep(5)
                else:
                    break
        except ValueError as error:
            return await send_response(context, content=f":warning: Invalid parameter: {error}", ephemeral=True)
        except aiohttp.ClientResponseError as error:
            log.exception(f"Failed request in host {guild.id}")
            return await send_response(context, content=":warning: Timed out! Bad response from host!", ephemeral=True)
        except aiohttp.ClientConnectorError:
            log.exception(f"Failed request in server {guild.id}")
            return await send_response(context, content=":warning: Timed out! Could not reach host!", ephemeral=True)
        except NotImplementedError:
            return await send_response(context, content=":warning: This method is not supported by the host!", ephemeral=True)
        except Exception:
            log.exception(f"Failed request in server {guild.id}")
            return await send_response(context, content=":warning: Something went wrong!", ephemeral=True)
        else:
            log.info("Finished generation")
        finally:
            self.generating[user.id] = False

        if response.is_nsfw and not channel.is_nsfw():
            return await send_response(context, content=f"🔞 Blocked NSFW image.", allowed_mentions=discord.AllowedMentions.none())

        use_embeds = await self.config.guild(guild).use_embeds()
        id = context.id if isinstance(context, discord.Interaction) else context.message.id
        filename = filename=f"image_{id}.{response.extension}"
        file = discord.File(io.BytesIO(response.data or b''), filename=filename, spoiler=response.is_nsfw)
        maxsize = await self.config.guild(guild).max_img2img()
        view = ImageActions(self, response.info_string, response.payload, user, channel, maxsize)
        embed = None
        if use_embeds:
            description = "\n".join([f"-# {line.strip()}" for line in message_content.split("\n")]) if message_content else None
            embed = discord.Embed(description=description, color=0x393A41)
            embed.set_image(url=f"attachment://{filename}")
            message_content = None
        elif message_content:
            message_content = "\n".join([f"*{line.strip()}*" for line in message_content.split("\n")]) if message_content else None

        msg = await send_response(context, content=message_content, embed=embed, file=file, view=view, allowed_mentions=discord.AllowedMentions.none())

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
