from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.types import Message, Receive, Scope, Send

from app.api import AnalyzeRequestGuardMiddleware, create_app
from app.config import Settings
from app.rate_limit import SlidingWindowRateLimiter
from app.schemas import JobArtifact
from app.vision.preprocess import encode_png
from tests.fixtures import build_synthetic_calendar, image_bytes


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": tmp_path,
        "job_ttl_seconds": 3600,
        "max_upload_bytes": 15 * 1024 * 1024,
        "max_image_pixels": 16_000_000,
        "analyze_rate_limit": 0,
        "rate_window_seconds": 3600,
        "cors_origins": (),
        "frontend_dir": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_health_routes_and_security_headers(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        for path in ("/health", "/api/health"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"


def test_full_analyze_grid_render_and_media_round_trip(tmp_path: Path) -> None:
    calendar = build_synthetic_calendar(theme="light")
    with TestClient(create_app(_settings(tmp_path))) as client:
        analyzed = client.post(
            "/api/analyze",
            files={"file": ("calendar.png", image_bytes(calendar), "image/png")},
        )
        assert analyzed.status_code == 200, analyzed.text
        body = analyzed.json()
        assert body["rows"] == 7
        assert body["cols"] == 53
        assert body["theme"] == "light"
        assert body["levels"] == 5
        assert body["absent_count"] == 0
        assert body["max_name_columns"] == 53
        assert body["palette"] == {
            str(index): color.upper() for index, color in enumerate(calendar.palette)
        }

        grid = client.get(f"/api/jobs/{body['job_id']}/grid")
        assert grid.status_code == 200
        grid_body = grid.json()
        assert len(grid_body["cells"]) == 7 * 53
        assert grid_body["absent_count"] == 0

        source = client.get(body["preview_original_url"])
        overlay = client.get(body["preview_overlay_url"])
        assert source.status_code == overlay.status_code == 200
        assert source.headers["content-type"] == "image/png"
        assert source.headers["x-content-type-options"] == "nosniff"

        rendered = client.post(
            "/api/render",
            json={
                "job_id": body["job_id"],
                "name": "JOBERNEY",
                "primary": "#163951",
                "secondary": "#F5A623",
                "outline": "#0A1620",
                "boldness": 2,
                "start": None,
            },
        )
        assert rendered.status_code == 200, rendered.text
        render_body = rendered.json()
        assert render_body["fit"] is True
        assert render_body["needed_cols"] == 47
        assert render_body["start"] == 3
        assert render_body["letter_cells"] == (
            render_body["overlap_cells"] + render_body["empty_letter_cells"]
        )

        downloaded = client.get(render_body["render_url"])
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(downloaded.content)) as image:
            assert image.mode == "RGB"
            assert image.width > 800

        repeated = client.post(
            "/api/render",
            json={
                "job_id": body["job_id"],
                "name": "JOBERNEY",
                "primary": "#163951",
                "secondary": "#F5A623",
                "outline": "#0A1620",
                "boldness": 2,
                "start": None,
            },
        )
        assert repeated.status_code == 200
        assert repeated.json() == render_body
        assert re.fullmatch(
            rf"/media/{body['job_id']}/render-[0-9a-f]{{24}}\.png",
            render_body["render_url"],
        )
        render_files = list((tmp_path / "jobs" / body["job_id"]).glob("render-*.png"))
        assert len(render_files) == 1


def test_upload_limits_empty_body_and_content_type_are_machine_readable(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path, max_upload_bytes=16))
    with TestClient(app) as client:
        too_large = client.post(
            "/api/analyze",
            files={"file": ("large.png", b"x" * 17, "image/png")},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "FILE_TOO_LARGE"

        empty = client.post(
            "/api/analyze",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert empty.status_code == 422
        assert empty.json()["code"] == "EMPTY_FILE"

    calendar = build_synthetic_calendar()
    with TestClient(create_app(_settings(tmp_path / "types"))) as client:
        mismatch = client.post(
            "/api/analyze",
            files={"file": ("calendar.png", image_bytes(calendar), "image/jpeg")},
        )
        assert mismatch.status_code == 415
        assert mismatch.json()["code"] == "CONTENT_TYPE_MISMATCH"

        unknown = client.post(
            "/api/analyze",
            files={"file": ("calendar.bin", image_bytes(calendar), "application/octet-stream")},
        )
        assert unknown.status_code == 415
        assert unknown.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_small_image_and_invalid_render_fields_return_stable_codes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        small_png = encode_png(Image.new("RGB", (199, 80), "white"))
        small = client.post(
            "/api/analyze",
            files={"file": ("small.png", small_png, "image/png")},
        )
        assert small.status_code == 422
        assert small.json()["code"] == "IMAGE_TOO_SMALL"

        base = {"job_id": "01JABCDEF01234567890123456", "name": "A"}
        cases = (
            ({**base, "name": "A!"}, "INVALID_NAME"),
            ({**base, "primary": "blue"}, "INVALID_COLOR"),
            ({**base, "boldness": 9}, "INVALID_BOLDNESS"),
            ({**base, "start": -1}, "INVALID_START"),
            ({**base, "unexpected": True}, "VALIDATION_ERROR"),
        )
        for payload, code in cases:
            response = client.post("/api/render", json=payload)
            assert response.status_code == 422
            assert response.json()["code"] == code

        expired = client.post("/api/render", json=base)
        assert expired.status_code == 422
        assert expired.json()["code"] == "JOB_EXPIRED"


def test_analyze_rate_limit_is_applied_before_image_work(tmp_path: Path) -> None:
    settings = _settings(tmp_path, analyze_rate_limit=1, rate_window_seconds=60)
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/analyze",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert first.json()["code"] == "EMPTY_FILE"

        second = client.post(
            "/api/analyze",
            content=b"this is not a multipart body",
            headers={"content-type": "multipart/form-data; boundary=missing"},
        )
        assert second.status_code == 429
        assert second.json()["code"] == "RATE_LIMITED"
        assert int(second.headers["retry-after"]) >= 1


def test_analyze_body_is_rejected_before_multipart_parsing_with_cors(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        max_analyze_body_bytes=64,
        cors_origins=("https://ui.example",),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/analyze",
            files={"file": ("oversized.png", b"x" * 100, "image/png")},
            headers={"origin": "https://ui.example"},
        )

    assert response.status_code == 413
    assert response.json() == {
        "code": "REQUEST_TOO_LARGE",
        "detail": "Analyze request body exceeds the configured limit",
        "max_bytes": 64,
    }
    assert response.headers["access-control-allow-origin"] == "https://ui.example"
    assert response.headers["cache-control"] == "no-store"


def test_render_body_is_rejected_before_json_parsing(tmp_path: Path) -> None:
    """A large JSON body must not be buffered and parsed before routing.

    Only analyze was guarded, so an oversized render body was read into memory
    and handed to ``json.loads`` before the route rejected it.
    """

    settings = _settings(tmp_path, max_json_body_bytes=256)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/render",
            content=b'{"job_id":"' + b"0" * 4096 + b'"}',
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {
        "code": "REQUEST_TOO_LARGE",
        "detail": "JSON request body exceeds the configured limit",
        "max_bytes": 256,
    }


def test_render_body_within_the_limit_still_reaches_validation(tmp_path: Path) -> None:
    """The guard must not disturb ordinary requests."""

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post("/api/render", json={"job_id": "nope"})

    assert response.status_code == 422
    # Reaching field validation at all proves the guard passed the body through.
    assert response.json()["code"] == "INVALID_NAME"


def test_render_rate_and_per_job_variant_limits_are_machine_readable(
    tmp_path: Path,
    small_job_artifact: JobArtifact,
) -> None:
    rate_app = create_app(_settings(tmp_path / "rate", render_rate_limit=1))
    rate_job = rate_app.state.job_store.create(small_job_artifact, b"source", b"overlay")
    base = {"job_id": rate_job, "name": "A"}
    with TestClient(rate_app) as client:
        assert client.post("/api/render", json=base).status_code == 200
        limited = client.post("/api/render", json=base)
    assert limited.status_code == 429
    assert limited.json()["code"] == "RENDER_RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1

    variant_app = create_app(_settings(tmp_path / "variants", max_render_variants_per_job=1))
    variant_job = variant_app.state.job_store.create(
        small_job_artifact,
        b"source",
        b"overlay",
    )
    with TestClient(variant_app) as client:
        first = client.post("/api/render", json={"job_id": variant_job, "name": "A"})
        second = client.post(
            "/api/render",
            json={"job_id": variant_job, "name": "A", "primary": "#654321"},
        )
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {
        "code": "RENDER_VARIANT_LIMIT",
        "detail": "This job has reached its render variant limit",
        "max_variants": 1,
    }


def test_name_validation_reports_type_blank_and_trimmed_length(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        base = {"job_id": "01JABCDEF01234567890123456"}
        cases = (
            (123, "name must be a string"),
            ("   ", "name must contain at least one letter or digit"),
            ("A" * 25, "name must contain 24 characters or fewer after trimming"),
            ("A!", "only A-Z, 0-9, space"),
        )
        for name, detail in cases:
            response = client.post("/api/render", json={**base, "name": name})
            assert response.status_code == 422
            assert response.json() == {"code": "INVALID_NAME", "detail": detail}


@pytest.mark.asyncio
async def test_chunked_analyze_body_is_bounded_without_content_length() -> None:
    async def consume_body(scope: Scope, receive: Receive, send: Send) -> None:
        del scope
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    guard = AnalyzeRequestGuardMiddleware(
        consume_body,
        max_body_bytes=5,
        concurrency=1,
        rate_limiter=SlidingWindowRateLimiter(0, 60),
    )
    incoming = iter(
        (
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        )
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(incoming)  # type: ignore[return-value]

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/analyze",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    }
    await guard(
        scope,
        receive,
        send,
    )

    assert sent[0]["status"] == 413
    assert b'"code":"REQUEST_TOO_LARGE"' in sent[1]["body"]


def test_client_ip_header_is_ignored_unless_configured(tmp_path: Path) -> None:
    """A forged edge header must not buy a fresh rate-limit budget by default."""

    settings = _settings(tmp_path, analyze_rate_limit=1, render_rate_limit=1)
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "203.0.113.1"},
        )
        second = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "203.0.113.2"},
        )

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json()["code"] == "RENDER_RATE_LIMITED"


def test_configured_client_ip_header_separates_callers(tmp_path: Path) -> None:
    """With the header opted into, each edge-reported address gets its own budget."""

    settings = _settings(
        tmp_path,
        analyze_rate_limit=1,
        render_rate_limit=1,
        client_ip_header="cf-connecting-ip",
    )
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "203.0.113.1"},
        )
        second = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "203.0.113.2"},
        )
        third = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "203.0.113.1"},
        )

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429


def test_unparseable_client_ip_header_falls_back_to_the_peer(tmp_path: Path) -> None:
    settings = _settings(tmp_path, render_rate_limit=1, client_ip_header="cf-connecting-ip")
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "not-an-ip"},
        )
        second = client.post(
            "/api/render",
            json={"job_id": "0" * 26, "name": "A"},
            headers={"cf-connecting-ip": "also-not-an-ip"},
        )

    assert first.status_code != 429
    assert second.status_code == 429
