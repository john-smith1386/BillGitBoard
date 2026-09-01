"""Filesystem-backed, expiring analysis job storage."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Final

from .errors import ServiceError
from .schemas import JobArtifact

_CROCKFORD: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_JOB_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_MEDIA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.png$")


def new_job_id(now_ms: int | None = None) -> str:
    """Return a 26-character ULID without adding a runtime dependency."""

    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    if timestamp < 0 or timestamp >= 2**48:
        raise ValueError("timestamp is outside ULID range")
    value = (timestamp << 80) | secrets.randbits(80)
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = _CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)


class JobStore:
    """Atomic JSON/image store with lazy TTL cleanup.

    Metadata remains private under the root.  The API resolves media through
    :meth:`media_path`, which only permits PNG names in a live job directory.
    """

    def __init__(
        self,
        root: Path | str,
        ttl_seconds: int = 86_400,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        max_render_variants: int = 20,
    ) -> None:
        self.root = Path(root).resolve()
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.max_render_variants = max(1, int(max_render_variants))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._last_cleanup = 0.0

    def _job_dir(self, job_id: str) -> Path:
        if not _JOB_ID_RE.fullmatch(job_id):
            raise ServiceError("JOB_EXPIRED", "Job does not exist or has expired")
        return self.root / job_id

    def create(
        self,
        artifact: JobArtifact,
        source_png: bytes,
        overlay_png: bytes,
    ) -> str:
        self.cleanup_if_due()
        metadata = self._json_bytes(artifact.model_dump(mode="json"))
        with self._lock:
            self._ensure_capacity_unlocked(len(source_png) + len(overlay_png) + len(metadata))
            for _ in range(4):
                job_id = new_job_id()
                job_dir = self.root / job_id
                try:
                    job_dir.mkdir(mode=0o700)
                    break
                except FileExistsError:
                    continue
            else:  # pragma: no cover - cryptographically implausible
                raise RuntimeError("could not allocate a unique job id")

            try:
                self._write_bytes_atomic(job_dir / "source.png", source_png)
                self._write_bytes_atomic(job_dir / "overlay.png", overlay_png)
                self._write_bytes_atomic(job_dir / "job.json", metadata)
            except Exception:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise
        return job_id

    def load(self, job_id: str) -> JobArtifact:
        job_dir = self._job_dir(job_id)
        metadata = job_dir / "job.json"
        try:
            stat = metadata.stat()
        except FileNotFoundError as exc:
            raise ServiceError("JOB_EXPIRED", "Job does not exist or has expired") from exc
        now = time.time()
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            artifact = JobArtifact.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ServiceError("JOB_EXPIRED", "Job artifact is unavailable") from exc
        created = min(float(artifact.created_at), stat.st_mtime)
        if now - created > self.ttl_seconds:
            self._remove_job(job_dir)
            raise ServiceError("JOB_EXPIRED", "Job does not exist or has expired")
        return artifact

    def save_render(self, job_id: str, filename: str, png: bytes) -> str:
        if not _MEDIA_RE.fullmatch(filename):
            raise ValueError("unsafe render filename")
        with self._lock:
            self.load(job_id)
            destination = self._job_dir(job_id) / filename
            if destination.is_file():
                return filename
            render_files = [
                path
                for path in self._job_dir(job_id).glob("*.png")
                if path.name not in {"source.png", "overlay.png"} and path.is_file()
            ]
            if len(render_files) >= self.max_render_variants:
                raise ServiceError(
                    "RENDER_VARIANT_LIMIT",
                    "This job has reached its render variant limit",
                    status_code=429,
                    max_variants=self.max_render_variants,
                )
            self._ensure_capacity_unlocked(len(png))
            self._write_bytes_atomic(destination, png)
        return filename

    def render_exists(self, job_id: str, filename: str) -> bool:
        if not _MEDIA_RE.fullmatch(filename):
            raise ValueError("unsafe render filename")
        self.load(job_id)
        return (self._job_dir(job_id) / filename).is_file()

    def media_path(self, job_id: str, filename: str) -> Path:
        self.load(job_id)
        if not _MEDIA_RE.fullmatch(filename):
            raise ServiceError("MEDIA_NOT_FOUND", "Media file not found", status_code=404)
        candidate = (self._job_dir(job_id) / filename).resolve()
        if candidate.parent != self._job_dir(job_id).resolve() or not candidate.is_file():
            raise ServiceError("MEDIA_NOT_FOUND", "Media file not found", status_code=404)
        return candidate

    def cleanup_if_due(self) -> int:
        now = time.time()
        interval = min(300.0, max(30.0, self.ttl_seconds / 8))
        if now - self._last_cleanup < interval:
            return 0
        with self._lock:
            if now - self._last_cleanup < interval:
                return 0
            self._last_cleanup = now
            return self.cleanup(now=now)

    def cleanup(self, *, now: float | None = None) -> int:
        cutoff = (time.time() if now is None else now) - self.ttl_seconds
        removed = 0
        with self._lock:
            for child in self.root.iterdir():
                if not child.is_dir() or not _JOB_ID_RE.fullmatch(child.name):
                    continue
                metadata = child / "job.json"
                try:
                    mtime = metadata.stat().st_mtime
                    payload = json.loads(metadata.read_text(encoding="utf-8"))
                    created = min(float(payload.get("created_at", mtime)), mtime)
                except (OSError, ValueError, json.JSONDecodeError):
                    created = child.stat().st_mtime
                if created < cutoff:
                    self._remove_job(child)
                    removed += 1
        return removed

    def usage_bytes(self) -> int:
        with self._lock:
            return self._usage_bytes_unlocked()

    def _usage_bytes_unlocked(self) -> int:
        total = 0
        for child in self.root.iterdir():
            if not child.is_dir() or not _JOB_ID_RE.fullmatch(child.name):
                continue
            for artifact in child.iterdir():
                try:
                    if artifact.is_file() and not artifact.is_symlink():
                        total += artifact.stat().st_size
                except FileNotFoundError:
                    continue
        return total

    def _ensure_capacity_unlocked(self, additional_bytes: int) -> None:
        used = self._usage_bytes_unlocked()
        if used + additional_bytes <= self.max_bytes:
            return
        # A throttled cleanup may have left newly expired artifacts in place.
        self.cleanup(now=time.time())
        used = self._usage_bytes_unlocked()
        if used + additional_bytes > self.max_bytes:
            raise ServiceError(
                "STORE_QUOTA_EXCEEDED",
                "The artifact store is full; try again after existing jobs expire",
                status_code=507,
                max_bytes=self.max_bytes,
                used_bytes=used,
                required_bytes=additional_bytes,
            )

    @staticmethod
    def _write_bytes_atomic(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _json_bytes(payload: dict[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    @staticmethod
    def _remove_job(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
