"""Environment-backed service configuration.

The module intentionally avoids a settings framework so importing the vision
library does not require constructing an application or touching the file
system.  ``Settings.from_env`` is called only by the API factory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_float(name: str, default: float, *, allow_zero: bool = False) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise RuntimeError(f"{name} must be {qualifier}")
    return value


def _positive_int(name: str, default: int, *, allow_zero: bool = False) -> int:
    value = _positive_float(name, float(default), allow_zero=allow_zero)
    if not value.is_integer():
        raise RuntimeError(f"{name} must be an integer")
    return int(value)


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path = Path("data")
    job_ttl_seconds: int = 24 * 60 * 60
    max_upload_bytes: int = 15 * 1024 * 1024
    max_image_pixels: int = 16_000_000
    max_analyze_body_bytes: int = 16 * 1024 * 1024
    max_json_body_bytes: int = 64 * 1024
    analyze_concurrency: int = 1
    render_concurrency: int = 2
    analyze_rate_limit: int = 20
    render_rate_limit: int = 120
    rate_window_seconds: int = 60 * 60
    max_render_variants_per_job: int = 20
    job_store_max_bytes: int = 512 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()
    client_ip_header: str = ""
    frontend_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("BILLGITBOARD_DATA_DIR", "data")).expanduser()
        ttl_hours = _positive_float("BILLGITBOARD_JOB_TTL_HOURS", 24)
        max_upload_mb = _positive_float("BILLGITBOARD_MAX_UPLOAD_MB", 15)
        max_body_mb = _positive_float(
            "BILLGITBOARD_MAX_ANALYZE_BODY_MB",
            max_upload_mb + 1,
        )
        if max_body_mb < max_upload_mb:
            raise RuntimeError(
                "BILLGITBOARD_MAX_ANALYZE_BODY_MB must be at least BILLGITBOARD_MAX_UPLOAD_MB"
            )
        store_max_mb = _positive_float("BILLGITBOARD_JOB_STORE_MAX_MB", 512)
        origins = tuple(
            origin.strip()
            for origin in os.getenv("BILLGITBOARD_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        frontend_value = os.getenv("BILLGITBOARD_FRONTEND_DIR", "").strip()
        client_ip_header = os.getenv("BILLGITBOARD_CLIENT_IP_HEADER", "").strip().lower()
        return cls(
            data_dir=data_dir,
            job_ttl_seconds=max(1, int(ttl_hours * 60 * 60)),
            max_upload_bytes=max(1, int(max_upload_mb * 1024 * 1024)),
            max_image_pixels=_positive_int("BILLGITBOARD_MAX_IMAGE_PIXELS", 16_000_000),
            max_analyze_body_bytes=max(1, int(max_body_mb * 1024 * 1024)),
            max_json_body_bytes=_positive_int("BILLGITBOARD_MAX_JSON_BODY_KB", 64) * 1024,
            analyze_concurrency=_positive_int("BILLGITBOARD_ANALYZE_CONCURRENCY", 1),
            render_concurrency=_positive_int("BILLGITBOARD_RENDER_CONCURRENCY", 2),
            analyze_rate_limit=_positive_int(
                "BILLGITBOARD_ANALYZE_RATE_LIMIT", 20, allow_zero=True
            ),
            render_rate_limit=_positive_int("BILLGITBOARD_RENDER_RATE_LIMIT", 120, allow_zero=True),
            rate_window_seconds=_positive_int("BILLGITBOARD_RATE_WINDOW_SECONDS", 3600),
            max_render_variants_per_job=_positive_int(
                "BILLGITBOARD_MAX_RENDER_VARIANTS_PER_JOB", 20
            ),
            job_store_max_bytes=max(1, int(store_max_mb * 1024 * 1024)),
            cors_origins=origins,
            client_ip_header=client_ip_header,
            frontend_dir=Path(frontend_value).expanduser() if frontend_value else None,
        )
