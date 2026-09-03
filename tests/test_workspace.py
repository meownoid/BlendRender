from __future__ import annotations

import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta

import blendrender.workspace as workspace_module
import pytest
from blendrender.config import Settings
from blendrender.models import (
    Backend,
    FrameResult,
    JobManifest,
    JobStatus,
    SceneManifest,
    UploadManifest,
    utc_now,
)
from blendrender.workspace import UPLOAD_CAPACITY_HEADROOM_BYTES, WorkspaceError, WorkspaceStore
from PIL import Image


def other_settings(settings: Settings) -> Settings:
    return Settings(
        app_password=settings.app_password,
        workspace_root=settings.workspace_root,
        pod_id="pod-b",
        blender_bin=settings.blender_bin,
        renderer_script=settings.renderer_script,
        frontend_dist=settings.frontend_dist,
        max_upload_bytes=settings.max_upload_bytes,
        upload_chunk_bytes=settings.upload_chunk_bytes,
        cookie_secure=settings.cookie_secure,
        session_ttl_seconds=settings.session_ttl_seconds,
        cancel_grace_seconds=settings.cancel_grace_seconds,
        available_backends_override=settings.available_backends_override,
    )


def create_scene(store: WorkspaceStore, identifier: str) -> None:
    staging = store.staging_path(identifier)
    (staging / "source").mkdir(parents=True)
    (staging / "source/input.blend").write_bytes(b"blend")
    store.create_scene(
        SceneManifest(
            id=identifier,
            filename="input.blend",
            source_kind="blend",
            entrypoint="input.blend",
            created_at=utc_now(),
            size_bytes=5,
        ),
        staging,
    )


def create_upload(store: WorkspaceStore, identifier: str, size_bytes: int = 5) -> None:
    now = datetime.now(UTC)
    store.create_upload(
        UploadManifest(
            id=identifier,
            filename="project.blend",
            name="project.blend",
            size_bytes=size_bytes,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat(),
        )
    )


def test_legacy_scene_manifest_uses_filename_as_name(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000200"
    create_scene(store, scene_id)
    manifest_path = store.scene_paths(scene_id)["manifest"]
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("name")
    manifest_path.write_text(json.dumps(manifest))

    assert store.get_scene(scene_id).name == "input.blend"


def test_workspace_json_is_pretty_printed(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()

    content = (settings.workspace_root / "workspace.json").read_text()

    assert content == json.dumps(json.loads(content), indent=2, sort_keys=True) + "\n"


def test_expired_upload_staging_is_removed(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    upload_id = "00000000-0000-4000-8000-000000000205"
    create_upload(store, upload_id)
    manifest_path = store.upload_paths(upload_id)["manifest"]
    payload = json.loads(manifest_path.read_text())
    expired = datetime.now(UTC) - timedelta(hours=25)
    payload["updated_at"] = expired.isoformat()
    payload["expires_at"] = expired.isoformat()
    manifest_path.write_text(json.dumps(payload))

    store.cleanup_expired_uploads()

    assert not store.upload_paths(upload_id)["root"].exists()


def test_open_uploads_reserve_their_remaining_capacity(settings, monkeypatch) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    free = UPLOAD_CAPACITY_HEADROOM_BYTES + 150
    usage_type = type(shutil.disk_usage(settings.workspace_root))
    monkeypatch.setattr(
        workspace_module.shutil,
        "disk_usage",
        lambda _: usage_type(free + 1, 1, free),
    )
    create_upload(store, "00000000-0000-4000-8000-000000000206", size_bytes=100)

    with pytest.raises(WorkspaceError, match="Insufficient disk space"):
        create_upload(store, "00000000-0000-4000-8000-000000000207", size_bytes=100)


def test_two_pods_share_scenes_but_claim_only_their_own_jobs(settings) -> None:
    first = WorkspaceStore(settings)
    second = WorkspaceStore(other_settings(settings))
    first.initialize()
    second.initialize()
    scene_id = "00000000-0000-4000-8000-000000000201"
    create_scene(first, scene_id)
    first.create_job(
        JobManifest(
            id="00000000-0000-4000-8000-000000000202",
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-a",
            mode="still",
            frame_start=1,
            frame_end=1,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    second.create_job(
        JobManifest(
            id="00000000-0000-4000-8000-000000000203",
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-b",
            mode="still",
            frame_start=1,
            frame_end=1,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    assert len(first.list_scenes()) == len(second.list_scenes()) == 1
    assert first.next_queued_job("pod-a").owner_pod_id == "pod-a"  # type: ignore[union-attr]
    assert second.next_queued_job("pod-b").owner_pod_id == "pod-b"  # type: ignore[union-attr]


def test_restart_marks_only_own_running_jobs_interrupted(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000211"
    create_scene(store, scene_id)
    job_id = "00000000-0000-4000-8000-000000000212"
    store.create_job(
        JobManifest(
            id=job_id,
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-a",
            mode="still",
            frame_start=1,
            frame_end=1,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    store.update_job(job_id, status=JobStatus.RUNNING)
    store.recover_owner_jobs("pod-a")
    assert store.get_job(job_id).status == JobStatus.INTERRUPTED


def test_stale_scene_lock_is_recovered(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000221"
    lock = settings.workspace_root / "locks" / "scenes" / scene_id
    lock.mkdir()
    os.utime(lock, (time.time() - 301, time.time() - 301))
    with store.scene_lock(scene_id):
        assert lock.is_dir()
    assert not lock.exists()


def test_results_are_invisible_until_complete_packages_are_published(settings) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000231"
    job_id = "00000000-0000-4000-8000-000000000232"
    create_scene(store, scene_id)
    store.create_job(
        JobManifest(
            id=job_id,
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-a",
            mode="still",
            frame_start=1,
            frame_end=1,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    for published_count, suffix in enumerate(("233", "234")):
        result_id = f"00000000-0000-4000-8000-000000000{suffix}"
        pending = store.job_paths(job_id)["pending"] / result_id
        pending.mkdir()
        Image.new("RGB", (8, 8), (0, 0, 0)).save(pending / "frame.png", "PNG")
        Image.new("RGB", (8, 8), (0, 0, 0)).save(pending / "preview.webp", "WEBP")
        assert len(store.list_results(scene_id)) == published_count
        store.publish_result(
            FrameResult(
                id=result_id,
                scene_id=scene_id,
                job_id=job_id,
                frame=1,
                pod_id="pod-a",
                backend=Backend.CPU,
                hardware=["CPU"],
                samples=1,
                render_seconds=0.1,
                completed_at=utc_now(),
            ),
            pending,
        )
    assert len(store.list_results(scene_id, frame=1)) == 2


def test_frame_pages_only_read_metadata_for_the_requested_frames(settings, monkeypatch) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000241"
    job_id = "00000000-0000-4000-8000-000000000242"
    create_scene(store, scene_id)
    store.create_job(
        JobManifest(
            id=job_id,
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-a",
            mode="range",
            frame_start=1,
            frame_end=3,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    for frame in range(1, 4):
        result_id = f"00000000-0000-4000-8000-{frame:012d}"
        pending = store.job_paths(job_id)["pending"] / result_id
        pending.mkdir()
        Image.new("RGB", (8, 8), (0, 0, 0)).save(pending / "frame.png", "PNG")
        Image.new("RGB", (8, 8), (0, 0, 0)).save(pending / "preview.webp", "WEBP")
        store.publish_result(
            FrameResult(
                id=result_id,
                scene_id=scene_id,
                job_id=job_id,
                frame=frame,
                pod_id="pod-a",
                backend=Backend.CPU,
                hardware=["CPU"],
                samples=1,
                render_seconds=0.1,
                completed_at=utc_now(),
            ),
            pending,
        )

    calls: list[int | None] = []
    list_results = store.list_results

    def record_list_results(scene_id: str, *, frame: int | None = None) -> list[FrameResult]:
        calls.append(frame)
        return list_results(scene_id, frame=frame)

    monkeypatch.setattr(store, "list_results", record_list_results)

    first_page = store.list_frame_groups(scene_id, cursor=None, limit=1)
    second_page = store.list_frame_groups(scene_id, cursor=first_page.next_cursor, limit=1)

    assert [group.frame for group in first_page.items] == [3]
    assert first_page.next_cursor == 3
    assert [group.frame for group in second_page.items] == [2]
    assert second_page.next_cursor == 2
    assert calls == [3, 2]
