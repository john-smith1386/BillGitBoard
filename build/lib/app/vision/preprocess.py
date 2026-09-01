"""Safe image decoding and scale-normalized preprocessing."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ServiceError

ACCEPTED_CONTENT_TYPES = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/webp": "WEBP",
}
ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP"}


@dataclass(frozen=True, slots=True)
class PreprocessedImage:
    rgb: np.ndarray
    filtered_rgb: np.ndarray
    lab: np.ndarray
    scale: float
    original_size: tuple[int, int]

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])


def decode_image(
    data: bytes,
    *,
    content_type: str | None,
    max_pixels: int = 16_000_000,
    longest_side: int = 2400,
) -> Image.Image:
    """Decode an accepted raster into a bounded, metadata-free RGB image.

    Dimension checks happen from the image header.  JPEG decoders are asked to
    subsample before loading, and every format is reduced with Pillow before a
    NumPy array is materialized by :func:`preprocess_image`.
    """

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type not in ACCEPTED_CONTENT_TYPES:
        raise ServiceError(
            "UNSUPPORTED_MEDIA_TYPE",
            "Upload a PNG, JPEG, or WebP image",
            status_code=415,
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                detected_format = (source.format or "").upper()
                width, height = source.size
                if detected_format not in ACCEPTED_FORMATS:
                    raise ServiceError(
                        "UNSUPPORTED_MEDIA_TYPE",
                        "The uploaded bytes are not PNG, JPEG, or WebP",
                        status_code=415,
                    )
                if detected_format != ACCEPTED_CONTENT_TYPES[normalized_type]:
                    raise ServiceError(
                        "CONTENT_TYPE_MISMATCH",
                        "The file content does not match its media type",
                        status_code=415,
                    )
                if width < 200 or height < 80:
                    raise ServiceError(
                        "IMAGE_TOO_SMALL",
                        "Image dimensions must be at least 200 x 80 pixels",
                        width=width,
                        height=height,
                    )
                if width * height > max_pixels:
                    raise ServiceError(
                        "IMAGE_TOO_LARGE",
                        "Decoded image dimensions are too large",
                        width=width,
                        height=height,
                    )
                original_size = (width, height)
                target_scale = min(1.0, longest_side / max(width, height))
                target_size = (
                    max(1, round(width * target_scale)),
                    max(1, round(height * target_scale)),
                )
                if detected_format == "JPEG" and target_scale < 1.0:
                    # JPEG draft mode selects a decoder-native 1/2, 1/4, or
                    # 1/8 reduction and avoids allocating the full RGB raster.
                    source.draft("RGB", target_size)
                source.load()
                oriented = ImageOps.exif_transpose(source)
                if max(oriented.size) > longest_side:
                    oriented.thumbnail(
                        (longest_side, longest_side),
                        Image.Resampling.LANCZOS,
                        reducing_gap=3.0,
                    )
                # Conversion creates independent pixels. Clearing ``info`` and
                # omitting save metadata strips EXIF, ICC, comments, and GPS.
                decoded = oriented.convert("RGB")
                decoded.info.clear()
                decoded._billgitboard_original_size = original_size  # type: ignore[attr-defined]
                return decoded
    except ServiceError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ServiceError("INVALID_IMAGE", "The uploaded image could not be decoded") from exc
    except Image.DecompressionBombWarning as exc:
        raise ServiceError("IMAGE_TOO_LARGE", "Decoded image dimensions are too large") from exc


def preprocess_image(image: Image.Image, *, longest_side: int = 2400) -> PreprocessedImage:
    rgb_image = image.convert("RGB")
    original_size = getattr(image, "_billgitboard_original_size", rgb_image.size)
    if max(rgb_image.size) > longest_side:
        resize_scale = longest_side / max(rgb_image.size)
        resized = (
            max(1, round(rgb_image.size[0] * resize_scale)),
            max(1, round(rgb_image.size[1] * resize_scale)),
        )
        rgb_image = rgb_image.resize(resized, Image.Resampling.LANCZOS)
    scale = max(rgb_image.size) / max(original_size)

    # ``asarray`` keeps a read-only view over Pillow's RGB buffer instead of
    # holding a second full-size Python copy.
    rgb = np.asarray(rgb_image, dtype=np.uint8)
    # A conservative bilateral pass suppresses JPEG speckle while preserving
    # the high-contrast edges used by the square-blob detector.
    filtered = cv2.bilateralFilter(rgb, d=5, sigmaColor=18, sigmaSpace=5)
    lab = cv2.cvtColor(filtered, cv2.COLOR_RGB2LAB)
    return PreprocessedImage(
        rgb=rgb,
        filtered_rgb=filtered,
        lab=lab,
        scale=scale,
        original_size=original_size,
    )


def encode_png(image: Image.Image | np.ndarray) -> bytes:
    if isinstance(image, np.ndarray):
        pil_image = Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB")
    else:
        pil_image = image.convert("RGB")
    output = BytesIO()
    pil_image.save(output, format="PNG", optimize=True)
    return output.getvalue()
