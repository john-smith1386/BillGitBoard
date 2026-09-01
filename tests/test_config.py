from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.rate_limit import SlidingWindowRateLimiter

ENV_NAMES = (
    "BILLGITBOARD_DATA_DIR",
    "BILLGITBOARD_JOB_TTL_HOURS",
    "BILLGITBOARD_MAX_UPLOAD_MB",
    "BILLGITBOARD_MAX_IMAGE_PIXELS",
    "BILLGITBOARD_MAX_ANALYZE_BODY_MB",
    "BILLGITBOARD_ANALYZE_CONCURRENCY",
    "BILLGITBOARD_ANALYZE_RATE_LIMIT",
    "BILLGITBOARD_RENDER_CONCURRENCY",
    "BILLGITBOARD_RENDER_RATE_LIMIT",
    "BILLGITBOARD_RATE_WINDOW_SECONDS",
    "BILLGITBOARD_MAX_RENDER_VARIANTS_PER_JOB",
    "BILLGITBOARD_JOB_STORE_MAX_MB",
    "BILLGITBOARD_CORS_ORIGINS",
    "BILLGITBOARD_FRONTEND_DIR",
)


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults_are_safe_and_documented(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)

    settings = Settings.from_env()

    assert settings.data_dir == Path("data")
    assert settings.job_ttl_seconds == 24 * 60 * 60
    assert settings.max_upload_bytes == 15 * 1024 * 1024
    assert settings.max_image_pixels == 16_000_000
    assert settings.max_analyze_body_bytes == 16 * 1024 * 1024
    assert settings.analyze_concurrency == 1
    assert settings.analyze_rate_limit == 20
    assert settings.render_concurrency == 2
    assert settings.render_rate_limit == 120
    assert settings.rate_window_seconds == 3600
    assert settings.max_render_variants_per_job == 20
    assert settings.job_store_max_bytes == 512 * 1024 * 1024
    assert settings.cors_origins == ()
    assert settings.frontend_dir is None


def test_settings_parse_explicit_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("BILLGITBOARD_DATA_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("BILLGITBOARD_JOB_TTL_HOURS", "1.5")
    monkeypatch.setenv("BILLGITBOARD_MAX_UPLOAD_MB", "2.5")
    monkeypatch.setenv("BILLGITBOARD_MAX_IMAGE_PIXELS", "123456")
    monkeypatch.setenv("BILLGITBOARD_MAX_ANALYZE_BODY_MB", "3")
    monkeypatch.setenv("BILLGITBOARD_ANALYZE_CONCURRENCY", "2")
    monkeypatch.setenv("BILLGITBOARD_ANALYZE_RATE_LIMIT", "0")
    monkeypatch.setenv("BILLGITBOARD_RENDER_CONCURRENCY", "3")
    monkeypatch.setenv("BILLGITBOARD_RENDER_RATE_LIMIT", "7")
    monkeypatch.setenv("BILLGITBOARD_RATE_WINDOW_SECONDS", "90")
    monkeypatch.setenv("BILLGITBOARD_MAX_RENDER_VARIANTS_PER_JOB", "4")
    monkeypatch.setenv("BILLGITBOARD_JOB_STORE_MAX_MB", "5.5")
    monkeypatch.setenv(
        "BILLGITBOARD_CORS_ORIGINS",
        " https://one.example,https://two.example ,,",
    )
    monkeypatch.setenv("BILLGITBOARD_FRONTEND_DIR", str(tmp_path / "dist"))

    settings = Settings.from_env()

    assert settings.data_dir == tmp_path / "jobs"
    assert settings.job_ttl_seconds == 5400
    assert settings.max_upload_bytes == int(2.5 * 1024 * 1024)
    assert settings.max_image_pixels == 123456
    assert settings.max_analyze_body_bytes == 3 * 1024 * 1024
    assert settings.analyze_concurrency == 2
    assert settings.analyze_rate_limit == 0
    assert settings.render_concurrency == 3
    assert settings.render_rate_limit == 7
    assert settings.rate_window_seconds == 90
    assert settings.max_render_variants_per_job == 4
    assert settings.job_store_max_bytes == int(5.5 * 1024 * 1024)
    assert settings.cors_origins == ("https://one.example", "https://two.example")
    assert settings.frontend_dir == tmp_path / "dist"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BILLGITBOARD_JOB_TTL_HOURS", "0"),
        ("BILLGITBOARD_MAX_UPLOAD_MB", "-1"),
        ("BILLGITBOARD_MAX_IMAGE_PIXELS", "1.5"),
        ("BILLGITBOARD_MAX_ANALYZE_BODY_MB", "0"),
        ("BILLGITBOARD_ANALYZE_CONCURRENCY", "0"),
        ("BILLGITBOARD_ANALYZE_RATE_LIMIT", "-1"),
        ("BILLGITBOARD_RENDER_CONCURRENCY", "0"),
        ("BILLGITBOARD_RENDER_RATE_LIMIT", "-1"),
        ("BILLGITBOARD_RATE_WINDOW_SECONDS", "not-a-number"),
        ("BILLGITBOARD_MAX_RENDER_VARIANTS_PER_JOB", "1.5"),
        ("BILLGITBOARD_JOB_STORE_MAX_MB", "0"),
    ],
)
def test_settings_reject_invalid_numeric_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        Settings.from_env()


def test_analyze_body_limit_cannot_be_smaller_than_file_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("BILLGITBOARD_MAX_UPLOAD_MB", "10")
    monkeypatch.setenv("BILLGITBOARD_MAX_ANALYZE_BODY_MB", "9")

    with pytest.raises(RuntimeError, match="BILLGITBOARD_MAX_ANALYZE_BODY_MB"):
        Settings.from_env()


def test_rate_limiter_reclaims_keys_after_their_window() -> None:
    """Distinct source addresses must not accumulate for the process lifetime.

    The previous cleanup branch was unreachable - it tested for an empty deque
    immediately after appending to it - so the map grew once per source address
    and never shrank.
    """

    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=60)
    for index in range(500):
        limiter.consume(f"10.0.0.{index}", now=1000.0)
    assert limiter.tracked_keys() == 500

    # One request a full window later sweeps every address that has aged out.
    limiter.consume("10.0.0.0", now=1000.0 + 61)
    assert limiter.tracked_keys() == 1


def test_rate_limiter_keeps_live_keys_while_sweeping() -> None:
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=60)
    limiter.consume("stale", now=1000.0)
    limiter.consume("fresh", now=1000.0 + 55)
    limiter.consume("trigger", now=1000.0 + 61)

    assert limiter.tracked_keys() == 2
    allowed, _ = limiter.consume("fresh", now=1000.0 + 62)
    assert allowed
