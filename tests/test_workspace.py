from __future__ import annotations

import os
import time

from blendrender.config import Settings
from blendrender.models import Backend, FrameResult, JobManifest, JobStatus, SceneManifest, utc_now
from blendrender.workspace import WorkspaceStore
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
