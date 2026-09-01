from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.errors import ServiceError
from app.jobs import JobStore, new_job_id
from app.schemas import JobArtifact


def test_new_job_id_is_a_sortable_crockford_ulid() -> None:
    earlier = new_job_id(now_ms=1_000)
    later = new_job_id(now_ms=2_000)

    assert len(earlier) == 26
    assert len(later) == 26
    assert earlier < later
    assert not ({"I", "L", "O", "U"} & set(earlier + later))


def test_store_round_trip_and_media_resolution(
    tmp_path: Path, small_job_artifact: JobArtifact
) -> None:
    store = JobStore(tmp_path / "jobs", ttl_seconds=60)
    job_id = store.create(small_job_artifact, b"source", b"overlay")

    loaded = store.load(job_id)
    assert loaded.cols == small_job_artifact.cols
    assert store.media_path(job_id, "source.png").read_bytes() == b"source"
    assert store.media_path(job_id, "overlay.png").read_bytes() == b"overlay"

    filename = store.save_render(job_id, "word-123.png", b"render")
    assert filename == "word-123.png"
    assert store.media_path(job_id, filename).read_bytes() == b"render"


@pytest.mark.parametrize(
    "filename",
    ["../secret.png", "nested/file.png", "render.jpg", ".hidden.png", "x" * 100 + ".png"],
)
def test_store_rejects_unsafe_render_names(
    tmp_path: Path, small_job_artifact: JobArtifact, filename: str
) -> None:
    store = JobStore(tmp_path / "jobs")
    job_id = store.create(small_job_artifact, b"source", b"overlay")

    with pytest.raises(ValueError, match="unsafe"):
        store.save_render(job_id, filename, b"render")


def test_media_path_does_not_allow_traversal(
    tmp_path: Path, small_job_artifact: JobArtifact
) -> None:
    store = JobStore(tmp_path / "jobs")
    job_id = store.create(small_job_artifact, b"source", b"overlay")

    with pytest.raises(ServiceError) as exc_info:
        store.media_path(job_id, "../source.png")

    assert exc_info.value.code == "MEDIA_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_load_removes_an_expired_job(tmp_path: Path, small_job_artifact: JobArtifact) -> None:
    artifact = small_job_artifact.model_copy(update={"created_at": time.time() - 120})
    store = JobStore(tmp_path / "jobs", ttl_seconds=60)
    job_id = store.create(artifact, b"source", b"overlay")

    with pytest.raises(ServiceError) as exc_info:
        store.load(job_id)

    assert exc_info.value.code == "JOB_EXPIRED"
    assert not (store.root / job_id).exists()


def test_cleanup_only_removes_expired_job_directories(
    tmp_path: Path, small_job_artifact: JobArtifact
) -> None:
    store = JobStore(tmp_path / "jobs", ttl_seconds=60)
    live_id = store.create(small_job_artifact, b"source", b"overlay")
    expired_id = store.create(small_job_artifact, b"source", b"overlay")
    old = time.time() - 120
    os.utime(store.root / expired_id / "job.json", (old, old))
    unrelated = store.root / "do-not-delete"
    unrelated.mkdir()

    removed = store.cleanup(now=time.time())

    assert removed == 1
    assert (store.root / live_id).is_dir()
    assert not (store.root / expired_id).exists()
    assert unrelated.is_dir()


def test_invalid_or_unknown_job_id_is_reported_as_expired(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")

    for job_id in ("../../etc/passwd", "01JABCDEF01234567890123456"):
        with pytest.raises(ServiceError) as exc_info:
            store.load(job_id)
        assert exc_info.value.code == "JOB_EXPIRED"


def test_render_variant_limit_is_idempotent_for_an_existing_filename(
    tmp_path: Path,
    small_job_artifact: JobArtifact,
) -> None:
    store = JobStore(tmp_path / "jobs", max_render_variants=1)
    job_id = store.create(small_job_artifact, b"source", b"overlay")

    assert store.save_render(job_id, "render-a.png", b"first") == "render-a.png"
    assert store.save_render(job_id, "render-a.png", b"ignored") == "render-a.png"
    assert store.media_path(job_id, "render-a.png").read_bytes() == b"first"

    with pytest.raises(ServiceError) as exc_info:
        store.save_render(job_id, "render-b.png", b"second")
    assert exc_info.value.code == "RENDER_VARIANT_LIMIT"
    assert exc_info.value.status_code == 429
    assert exc_info.value.extra == {"max_variants": 1}


def test_global_store_quota_bounds_new_jobs_and_renders(
    tmp_path: Path,
    small_job_artifact: JobArtifact,
) -> None:
    full = JobStore(tmp_path / "full", max_bytes=1)
    with pytest.raises(ServiceError) as create_error:
        full.create(small_job_artifact, b"source", b"overlay")
    assert create_error.value.code == "STORE_QUOTA_EXCEEDED"
    assert create_error.value.status_code == 507
    assert not any(full.root.iterdir())

    store = JobStore(tmp_path / "render", max_bytes=1_000_000)
    job_id = store.create(small_job_artifact, b"source", b"overlay")
    used = store.usage_bytes()
    store.max_bytes = used + 4
    with pytest.raises(ServiceError) as render_error:
        store.save_render(job_id, "render-a.png", b"12345")
    assert render_error.value.code == "STORE_QUOTA_EXCEEDED"
    assert render_error.value.status_code == 507
    assert render_error.value.extra["used_bytes"] == used
    assert not (store.root / job_id / "render-a.png").exists()
