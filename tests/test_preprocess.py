from __future__ import annotations

import struct
import zlib
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from app.errors import ServiceError
from app.vision.preprocess import decode_image, encode_png, preprocess_image
from tests.fixtures import build_synthetic_calendar, image_bytes


def test_decode_accepts_png_jpeg_and_webp_and_returns_fresh_rgb() -> None:
    calendar = build_synthetic_calendar()
    cases = (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"))

    for image_format, content_type in cases:
        decoded = decode_image(
            image_bytes(calendar, image_format),
            content_type=content_type,
        )
        assert decoded.mode == "RGB"
        assert decoded.size == calendar.image.size
        assert decoded.getexif() == {}


def test_decode_rejects_declared_and_detected_type_mismatch() -> None:
    data = image_bytes(build_synthetic_calendar(), "PNG")

    with pytest.raises(ServiceError) as exc_info:
        decode_image(data, content_type="image/jpeg")

    assert exc_info.value.code == "CONTENT_TYPE_MISMATCH"
    assert exc_info.value.status_code == 415


def test_decode_rejects_unknown_media_type_before_inspecting_bytes() -> None:
    with pytest.raises(ServiceError) as exc_info:
        decode_image(b"not an image", content_type="application/octet-stream")

    assert exc_info.value.code == "UNSUPPORTED_MEDIA_TYPE"
    assert exc_info.value.status_code == 415


def test_decode_rejects_invalid_bytes_and_small_or_excessive_dimensions() -> None:
    with pytest.raises(ServiceError) as invalid:
        decode_image(b"not png", content_type="image/png")
    assert invalid.value.code == "INVALID_IMAGE"

    too_small = Image.new("RGB", (199, 80), "white")
    with pytest.raises(ServiceError) as small:
        decode_image(encode_png(too_small), content_type="image/png")
    assert small.value.code == "IMAGE_TOO_SMALL"

    valid = Image.new("RGB", (200, 80), "white")
    with pytest.raises(ServiceError) as large:
        decode_image(encode_png(valid), content_type="image/png", max_pixels=15_999)
    assert large.value.code == "IMAGE_TOO_LARGE"


def test_pixel_bomb_is_rejected_from_png_header_before_raster_decode() -> None:
    encoded = bytearray(encode_png(Image.new("RGB", (200, 80), "white")))
    # Rewrite IHDR dimensions and its CRC. The compressed pixels intentionally
    # remain tiny/inconsistent: a safe decoder must reject from the header
    # before attempting to allocate or inflate a 40-million-pixel raster.
    struct.pack_into(">II", encoded, 16, 8_000, 5_000)
    struct.pack_into(">I", encoded, 29, zlib.crc32(encoded[12:29]))

    with pytest.raises(ServiceError) as exc_info:
        decode_image(bytes(encoded), content_type="image/png", max_pixels=16_000_000)

    assert exc_info.value.code == "IMAGE_TOO_LARGE"
    assert exc_info.value.extra == {"width": 8_000, "height": 5_000}


def test_preprocess_downscales_by_longest_side_and_tracks_scale() -> None:
    image = Image.new("RGB", (3000, 1200), "#123456")

    processed = preprocess_image(image, longest_side=2400)

    assert processed.original_size == (3000, 1200)
    assert processed.scale == pytest.approx(0.8)
    assert (processed.width, processed.height) == (2400, 960)
    assert processed.rgb.shape == (960, 2400, 3)
    assert processed.filtered_rgb.shape == processed.rgb.shape
    assert processed.lab.shape == processed.rgb.shape
    assert processed.rgb.dtype == np.uint8


def test_encode_png_outputs_rgb_without_source_metadata() -> None:
    image = Image.new("RGB", (200, 80), "red")
    image.info["comment"] = b"private"

    encoded = encode_png(image)
    with Image.open(BytesIO(encoded)) as reopened:
        assert reopened.format == "PNG"
        assert reopened.mode == "RGB"
        assert "comment" not in reopened.info
