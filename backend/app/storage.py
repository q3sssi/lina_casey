import io
import uuid
import warnings
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings

Image.MAX_IMAGE_PIXELS = 25_000_000  # защита от decompression bomb
warnings.simplefilter("error", Image.DecompressionBombWarning)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_image(file: UploadFile, folder: str, size: int, square: bool = False) -> str:
    """Проверяет файл по содержимому (не по Content-Type), ресайзит и перекодирует в WebP.
    Перекодирование вырезает EXIF/GPS и любой «полиглот»-payload. Возвращает путь внутри upload_dir."""
    limit = settings.max_upload_mb * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ValueError("format")
        img = ImageOps.exif_transpose(img)
        if square:
            img = ImageOps.fit(img, (size, size))
        img.thumbnail((size, size))
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(415, "Unsupported or corrupted image (jpeg/png/webp only)")
    rel = f"{folder}/{uuid.uuid4().hex}.webp"
    dest = Path(settings.upload_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "WEBP", quality=85)
    return rel


def delete_file(rel: str | None) -> None:
    if not rel:
        return
    root = Path(settings.upload_dir).resolve()
    path = (root / rel).resolve()
    if path.is_relative_to(root):  # защита от path traversal
        path.unlink(missing_ok=True)
