from enum import Enum
from typing import Optional

from aimage.common.params import ImageGenParams


class ImageGenerationType(Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"


class BaseAPI():
    def __init__(self):
        pass

    async def _init(self):
        raise NotImplementedError

    async def update_autocomplete_cache(self, cache: dict):
        raise NotImplementedError

    async def generate_image(self, params: Optional[ImageGenParams] = None, payload: Optional[dict] = None):
        raise NotImplementedError
    
    async def force_close(self):
        raise NotImplementedError
