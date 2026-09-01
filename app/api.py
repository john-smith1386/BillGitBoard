"""FastAPI entrypoint for analysis, deterministic rendering, and media."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.config import Settings
from app.errors import ServiceError
from app.jobs import JobStore
from app.rate_limit import SlidingWindowRateLimiter
from app.render.calendar import render_calendar
from app.schemas import (
    AnalyzeResponse,
    GridDumpResponse,
    RenderRequest,
    RenderResponse,
)
from app.text.layout import layout_name
from app.vision.pipeline import analyze_image
from app.vision.preprocess import decode_image

LOGGER = logging.getLogger("billgitboard.api")


class _AnalyzeBodyTooLarge(Exception):
    pass


class _RenderBodyTooLarge(Exception):
    pass


async def _send_guard_error(
    send: Send,
    *,
    status: int,
    code: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Emit a guard rejection before any route or parser has run."""

    payload: dict[str, Any] = {"code": code, "detail": detail}
    payload.update(extra or {})
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
                (b"x-frame-options", b"DENY"),
                (b"referrer-policy", b"no-referrer"),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class AnalyzeRequestGuardMiddleware:
    """Rate-limit, bound, and serialize analyze before multipart parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        concurrency: int,
        rate_limiter: SlidingWindowRateLimiter,
        client_ip_header: str = "",
    ) -> None:
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))
        self.semaphore = asyncio.Semaphore(max(1, int(concurrency)))
        self.rate_limiter = rate_limiter
        self.client_ip_header = client_ip_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/analyze"
        ):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", ()) if name.lower() == b"content-length"
        ]
        if content_lengths:
            try:
                content_length = int(content_lengths[-1])
            except ValueError:
                await _send_guard_error(
                    send,
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    detail="Content-Length must be a non-negative integer",
                )
                return
            if content_length < 0:
                await _send_guard_error(
                    send,
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    detail="Content-Length must be a non-negative integer",
                )
                return
            if content_length > self.max_body_bytes:
                await _send_guard_error(
                    send,
                    status=413,
                    code="REQUEST_TOO_LARGE",
                    detail="Analyze request body exceeds the configured limit",
                    extra={"max_bytes": self.max_body_bytes},
                )
                return

        client = scope.get("client")
        header_value: str | None = None
        if self.client_ip_header:
            wanted = self.client_ip_header.encode("latin-1")
            for name, value in scope.get("headers", ()):
                if name.lower() == wanted:
                    header_value = value.decode("latin-1")
                    break
        client_key = _resolve_client_ip(header_value, str(client[0]) if client else None)
        allowed, retry_after = self.rate_limiter.consume(client_key)
        if not allowed:
            await _send_guard_error(
                send,
                status=429,
                code="RATE_LIMITED",
                detail="Analyze limit reached; try again later",
                extra={"retry_after": retry_after},
                headers=[(b"retry-after", str(retry_after).encode("ascii"))],
            )
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _AnalyzeBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async with self.semaphore:
            try:
                await self.app(scope, limited_receive, tracked_send)
            except _AnalyzeBodyTooLarge:
                if response_started:  # pragma: no cover - analyze parses before response
                    raise
                await _send_guard_error(
                    send,
                    status=413,
                    code="REQUEST_TOO_LARGE",
                    detail="Analyze request body exceeds the configured limit",
                    extra={"max_bytes": self.max_body_bytes},
                )


class JsonBodyGuardMiddleware:
    """Bound the JSON request body before Starlette buffers and parses it.

    Only analyze was guarded before, so a render request of any size was read
    into memory and handed to ``json.loads`` on the event loop before routing.
    A valid render request is a job id, a short name, three hex colors and two
    integers, so the ceiling is generous at a few kilobytes; the point is that
    a single oversized body cannot exhaust a small instance's memory.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, paths: frozenset[str]) -> None:
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))
        self.paths = paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") in self.paths
        ):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", ()) if name.lower() == b"content-length"
        ]
        if content_lengths:
            try:
                content_length = int(content_lengths[-1])
            except ValueError:
                await _send_guard_error(
                    send,
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    detail="Content-Length must be a non-negative integer",
                )
                return
            if content_length < 0:
                await _send_guard_error(
                    send,
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    detail="Content-Length must be a non-negative integer",
                )
                return
            if content_length > self.max_body_bytes:
                await _send_guard_error(
                    send,
                    status=413,
                    code="REQUEST_TOO_LARGE",
                    detail="JSON request body exceeds the configured limit",
                    extra={"max_bytes": self.max_body_bytes},
                )
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _RenderBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RenderBodyTooLarge:
            if response_started:  # pragma: no cover - the body is read before any response
                raise
            await _send_guard_error(
                send,
                status=413,
                code="REQUEST_TOO_LARGE",
                detail="JSON request body exceeds the configured limit",
                extra={"max_bytes": self.max_body_bytes},
            )


def _resolve_client_ip(header_value: str | None, peer: str | None) -> str:
    """Return the rate-limit key for one request.

    By default the key is the peer address uvicorn resolved, which already
    accounts for ``--forwarded-allow-ips``; raw X-Forwarded-For is never parsed
    here because its leftmost entry is client-supplied.

    ``BILLGITBOARD_CLIENT_IP_HEADER`` opts into trusting one edge-set header
    instead, for platforms that publish the true client address that way
    (``cf-connecting-ip`` behind Cloudflare, for instance). It is empty by
    default and must stay empty unless the edge in front of this service
    overwrites that header on every request: anywhere it does not, a client can
    set it freely and each forged value gets its own rate-limit budget.
    """

    if header_value:
        candidate = header_value.split(",")[0].strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            pass
        else:
            return candidate
    return peer or "unknown"


def _client_key(request: Request) -> str:
    header_name: str = getattr(request.app.state, "client_ip_header", "")
    return _resolve_client_ip(
        request.headers.get(header_name) if header_name else None,
        request.client.host if request.client else None,
    )


async def _read_upload(file: UploadFile, limit: int) -> bytes:
    size = getattr(file, "size", None)
    if isinstance(size, int) and size > limit:
        raise ServiceError(
            "FILE_TOO_LARGE",
            f"Upload exceeds the {limit // (1024 * 1024)} MB limit",
            status_code=413,
            max_bytes=limit,
        )
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ServiceError(
                    "FILE_TOO_LARGE",
                    f"Upload exceeds the {limit // (1024 * 1024)} MB limit",
                    status_code=413,
                    max_bytes=limit,
                )
            chunks.append(chunk)
    finally:
        await file.close()
    if not chunks:
        raise ServiceError("EMPTY_FILE", "Upload an image file")
    return b"".join(chunks)


def _validation_response(error: RequestValidationError) -> JSONResponse:
    errors = error.errors()
    fields = {str(item.get("loc", ("",))[-1]) for item in errors}
    if "name" in fields:
        name_errors = [item for item in errors if item.get("loc", ("",))[-1] == "name"]
        messages = " ".join(str(item.get("msg", "")).lower() for item in name_errors)
        if any(item.get("type") == "string_type" for item in name_errors):
            detail = "name must be a string"
        elif "24 characters or fewer" in messages:
            detail = "name must contain 24 characters or fewer after trimming"
        elif "at least one letter or digit" in messages:
            detail = "name must contain at least one letter or digit"
        else:
            detail = "only A-Z, 0-9, space"
        body = {"code": "INVALID_NAME", "detail": detail}
    elif fields & {"primary", "secondary", "outline"}:
        body = {"code": "INVALID_COLOR", "detail": "colors must use #RRGGBB"}
    elif "boldness" in fields:
        body = {"code": "INVALID_BOLDNESS", "detail": "boldness must be an integer from 0 to 8"}
    elif "start" in fields:
        body = {"code": "INVALID_START", "detail": "start must be null or a non-negative integer"}
    else:
        body = {"code": "VALIDATION_ERROR", "detail": errors}
    return JSONResponse(body, status_code=422)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs_root = settings.data_dir.resolve() / "jobs"
    store = JobStore(
        jobs_root,
        settings.job_ttl_seconds,
        max_bytes=settings.job_store_max_bytes,
        max_render_variants=settings.max_render_variants_per_job,
    )
    analyze_limiter = SlidingWindowRateLimiter(
        settings.analyze_rate_limit,
        settings.rate_window_seconds,
    )
    render_limiter = SlidingWindowRateLimiter(
        settings.render_rate_limit,
        settings.rate_window_seconds,
    )
    render_semaphore = asyncio.Semaphore(settings.render_concurrency)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        await run_in_threadpool(store.cleanup)
        yield
        await run_in_threadpool(store.cleanup_if_due)

    application = FastAPI(
        title="BillGitBoard API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.client_ip_header = settings.client_ip_header
    application.state.job_store = store
    application.state.rate_limiter = analyze_limiter
    application.state.analyze_rate_limiter = analyze_limiter
    application.state.render_rate_limiter = render_limiter
    application.state.render_semaphore = render_semaphore

    @application.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(
            error.as_dict(),
            status_code=error.status_code,
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _validation_response(error)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Added after the function middleware so this pure ASGI guard is outermost
    # and controls receive() before Starlette constructs UploadFile objects.
    application.add_middleware(
        AnalyzeRequestGuardMiddleware,
        max_body_bytes=settings.max_analyze_body_bytes,
        concurrency=settings.analyze_concurrency,
        rate_limiter=analyze_limiter,
        client_ip_header=settings.client_ip_header,
    )
    # Render and any future JSON route are bounded before Starlette buffers the
    # body. Analyze keeps its own, much larger, multipart limit above.
    application.add_middleware(
        JsonBodyGuardMiddleware,
        max_body_bytes=settings.max_json_body_bytes,
        paths=frozenset({"/api/render"}),
    )
    # CORS remains outermost so pre-parser 413/429 responses are readable by
    # an explicitly allowed split-origin browser UI.
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @application.get("/health", tags=["operations"])
    @application.get("/api/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.post("/api/analyze", response_model=AnalyzeResponse, tags=["calendar"])
    async def analyze(request: Request, file: UploadFile) -> AnalyzeResponse:
        del request  # AnalyzeRequestGuardMiddleware consumed the client quota.
        started = time.perf_counter()
        data = await _read_upload(file, settings.max_upload_bytes)
        image = await run_in_threadpool(
            decode_image,
            data,
            content_type=file.content_type,
            max_pixels=settings.max_image_pixels,
        )
        result = await run_in_threadpool(analyze_image, image)
        job_id = await run_in_threadpool(
            store.create,
            result.artifact,
            result.source_png,
            result.overlay_png,
        )
        absent_count = sum(not cell.present for cell in result.artifact.cells)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        LOGGER.info(
            "analysis_complete job_id=%s cols=%d shades=%d elapsed_ms=%d",
            job_id,
            result.artifact.cols,
            result.artifact.levels,
            elapsed_ms,
        )
        return AnalyzeResponse(
            job_id=job_id,
            rows=7,
            cols=result.artifact.cols,
            theme=result.artifact.theme,
            levels=result.artifact.levels,
            palette=result.artifact.palette,
            absent_count=absent_count,
            preview_original_url=f"/media/{job_id}/source.png",
            preview_overlay_url=f"/media/{job_id}/overlay.png",
            max_name_columns=result.artifact.cols,
            warnings=result.artifact.warnings,
        )

    @application.post("/api/render", response_model=RenderResponse, tags=["calendar"])
    async def render(request: Request, payload: RenderRequest) -> RenderResponse:
        allowed, retry_after = render_limiter.consume(_client_key(request))
        if not allowed:
            raise ServiceError(
                "RENDER_RATE_LIMITED",
                "Render limit reached; try again later",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                retry_after=retry_after,
            )
        started = time.perf_counter()
        artifact = await run_in_threadpool(store.load, payload.job_id)
        present = [[False] * artifact.cols for _ in range(7)]
        for cell in artifact.cells:
            present[cell.r][cell.c] = cell.present
        layout = layout_name(payload.name, artifact.cols, present, payload.start)
        canonical_options = json.dumps(
            {
                "renderer_version": 1,
                "name": layout.name,
                "primary": payload.primary,
                "secondary": payload.secondary,
                "outline": payload.outline,
                "boldness": payload.boldness,
                "start": layout.start,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        digest = hashlib.sha256(canonical_options).hexdigest()[:24]
        filename = f"render-{digest}.png"
        cached = await run_in_threadpool(store.render_exists, payload.job_id, filename)
        letter_cells = layout.letter_cells
        overlap_cells = sum(
            1
            for cell in artifact.cells
            if cell.present and layout.letter_id[cell.r, cell.c] > 0 and cell.level > 0
        )
        empty_letter_cells = letter_cells - overlap_cells
        if cached:
            return RenderResponse(
                fit=True,
                needed_cols=layout.needed_cols,
                start=layout.start,
                letter_cells=letter_cells,
                overlap_cells=overlap_cells,
                empty_letter_cells=empty_letter_cells,
                render_url=f"/media/{payload.job_id}/{filename}",
            )
        async with render_semaphore:
            # Another request may have completed this deterministic variant
            # while this request waited for the bounded render slot.
            cached = await run_in_threadpool(store.render_exists, payload.job_id, filename)
            if cached:
                return RenderResponse(
                    fit=True,
                    needed_cols=layout.needed_cols,
                    start=layout.start,
                    letter_cells=letter_cells,
                    overlap_cells=overlap_cells,
                    empty_letter_cells=empty_letter_cells,
                    render_url=f"/media/{payload.job_id}/{filename}",
                )
            rendered = await run_in_threadpool(
                render_calendar,
                artifact,
                layout,
                primary=payload.primary,
                secondary=payload.secondary,
                outline=payload.outline,
                boldness=payload.boldness,
            )
            await run_in_threadpool(store.save_render, payload.job_id, filename, rendered.png)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        LOGGER.info(
            "render_complete job_id=%s name_length=%d elapsed_ms=%d",
            payload.job_id,
            len(layout.name),
            elapsed_ms,
        )
        return RenderResponse(
            fit=True,
            needed_cols=layout.needed_cols,
            start=layout.start,
            letter_cells=rendered.letter_cells,
            overlap_cells=rendered.overlap_cells,
            empty_letter_cells=rendered.empty_letter_cells,
            render_url=f"/media/{payload.job_id}/{filename}",
        )

    @application.get(
        "/api/jobs/{job_id}/grid",
        response_model=GridDumpResponse,
        tags=["calendar"],
    )
    async def grid(job_id: str) -> GridDumpResponse:
        artifact = await run_in_threadpool(store.load, job_id)
        return GridDumpResponse(
            job_id=job_id,
            rows=7,
            cols=artifact.cols,
            theme=artifact.theme,
            levels=artifact.levels,
            palette=artifact.palette,
            panel_color=artifact.panel_color,
            absent_count=sum(not cell.present for cell in artifact.cells),
            cells=artifact.cells,
            warnings=artifact.warnings,
        )

    @application.get("/media/{job_id}/{filename}", include_in_schema=False)
    async def media(job_id: str, filename: str) -> FileResponse:
        path = await run_in_threadpool(store.media_path, job_id, filename)
        return FileResponse(
            path,
            media_type="image/png",
            filename=filename,
            content_disposition_type="inline",
            headers={
                "Cache-Control": f"private, max-age={min(settings.job_ttl_seconds, 86400)}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    frontend_dir: Path | None = settings.frontend_dir
    if frontend_dir is not None:
        resolved_frontend = frontend_dir.resolve()
        if not (resolved_frontend / "index.html").is_file():
            raise RuntimeError("BILLGITBOARD_FRONTEND_DIR must contain a built index.html")
        application.mount(
            "/",
            StaticFiles(directory=resolved_frontend, html=True),
            name="frontend",
        )
    return application


app = create_app()
