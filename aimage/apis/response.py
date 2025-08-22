
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImageResponse:
    data: Optional[bytes] = None
    payload: dict = field(default_factory=dict)
    is_nsfw: bool = False
    info_string: str = ""
    extension: str = "png"
