from typing import Tuple

from PIL import Image as ImageModule
from PIL.Image import Image
from fastapi import UploadFile


def to_pil_image(img_file: UploadFile, mode: str = "RGB") -> Image:
    img: Image = ImageModule.open(img_file.file)
    return img.convert(mode)


def thumbnail(img: Image, size: Tuple[int, int]) -> Image:
    return img.thumbnail(size)
