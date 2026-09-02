from __future__ import annotations

import io
import time
import zipfile
from dataclasses import replace

from blendrender.main import create_app
from blendrender.models import Backend, FrameResult, JobManifest, SceneManifest, utc_now
from blendrender.workspace import WorkspaceStore
from fastapi.testclient import TestClient
from PIL import Image


def login(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200


def upload_scene(
    client: TestClient,
    filename: str = "scene.blend",
    content: bytes = b"blend",
    name: str | None = None,
) -> dict:
    created = client.post(
        "/api/uploads",
        json={"filename": filename, "name": name, "size_bytes": len(content)},
    )
    assert created.status_code == 201, created.text
    upload = created.json()
    offset = 0
    while offset < len(content):
        chunk = content[offset : offset + upload["chunk_size_bytes"]]
        appended = client.patch(
            f"/api/uploads/{upload['id']}",
            content=chunk,
            headers={
                "Content-Type": "application/octet-stream",
                "Upload-Offset": str(offset),
            },
        )
        assert appended.status_code == 200, appended.text
        offset = appended.json()["uploaded_bytes"]
    complete = client.post(f"/api/uploads/{upload['id']}/complete")
    assert complete.status_code == 202, complete.text
    for _ in range(100):
        status = client.get(f"/api/uploads/{upload['id']}")
        assert status.status_code == 200, status.text
        upload = status.json()
        if upload["status"] == "completed" and upload["scene"] is not None:
            return upload["scene"]
        assert upload["status"] != "failed", upload["error"]
        time.sleep(0.01)
    raise AssertionError("upload did not finalize")


def test_scene_upload_then_local_job_creation(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        scene = upload_scene(client)
        assert scene["filename"] == "input.blend"
        assert scene["name"] == "scene.blend"
        created = client.post(
            "/api/jobs",
            json={
                "scene_id": scene["id"],
                "mode": "range",
                "start": 1,
                "end": 3,
                "backend": "OPTIX",
                "tile_size": 256,
            },
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["owner_pod_id"] == "pod-a"
        assert job["scene_id"] == scene["id"]
        assert job["tile_size"] == 256
        assert client.get("/api/scenes").json()[0]["job_count"] == 1


def test_job_creation_rejects_an_out_of_range_tile_size(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        scene = upload_scene(client)
        response = client.post(
            "/api/jobs",
            json={
                "scene_id": scene["id"],
                "mode": "still",
                "frame": 1,
                "backend": "CPU",
                "tile_size": 7,
            },
        )

        assert response.status_code == 422
        assert "greater than or equal to 8" in response.text


def test_scene_upload_uses_optional_name_and_sanitizes_fallback(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        named = upload_scene(client, "source.blend", name="  ../ Hero\tShot  ")
        fallback = upload_scene(client, "folder\\Forest Scene.blend", name="   ")

        assert named["name"] == "Hero Shot"
        assert fallback["name"] == "Forest Scene.blend"


def test_zip_scene_preserves_entrypoint_and_resources(settings) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project/main.blend", b"blend")
        archive.writestr("project/textures/a.png", b"png")
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        scene = upload_scene(client, "project.zip", payload.getvalue())
        assert scene["filename"] == "main.blend"
        store = WorkspaceStore(settings)
        entrypoint, root = store.scene_entrypoint(scene["id"])
        assert entrypoint == root / "project/main.blend"
        assert (root / "project/textures/a.png").read_bytes() == b"png"


def test_upload_chunks_resume_from_the_committed_offset(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        created = client.post(
            "/api/uploads",
            json={"filename": "scene.blend", "size_bytes": 5},
        )
        assert created.status_code == 201
        upload = created.json()
        first = client.patch(
            f"/api/uploads/{upload['id']}",
            content=b"bl",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "0"},
        )
        assert first.status_code == 200
        assert first.json()["uploaded_bytes"] == 2
        stale = client.patch(
            f"/api/uploads/{upload['id']}",
            content=b"end",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "0"},
        )
        assert stale.status_code == 409
        assert stale.headers["upload-offset"] == "2"
        resumed = client.patch(
            f"/api/uploads/{upload['id']}",
            content=b"end",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "2"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["uploaded_bytes"] == 5


def test_upload_chunk_size_is_configured_and_enforced(settings) -> None:
    app = create_app(replace(settings, upload_chunk_bytes=2), start_worker=False)
    with TestClient(app) as client:
        login(client)
        created = client.post(
            "/api/uploads",
            json={"filename": "scene.blend", "size_bytes": 5},
        )
        assert created.status_code == 201
        upload = created.json()
        assert upload["chunk_size_bytes"] == 2
        rejected = client.patch(
            f"/api/uploads/{upload['id']}",
            content=b"abc",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "0"},
        )
        assert rejected.status_code == 413


def test_upload_rejects_incomplete_finalization_and_can_be_deleted(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        created = client.post(
            "/api/uploads",
            json={"filename": "scene.blend", "size_bytes": 5},
        )
        upload_id = created.json()["id"]
        incomplete = client.post(f"/api/uploads/{upload_id}/complete")
        assert incomplete.status_code == 422
        assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
        assert client.get(f"/api/uploads/{upload_id}").status_code == 404


def test_upload_session_persists_across_an_application_restart(settings) -> None:
    first = create_app(settings, start_worker=False)
    with TestClient(first) as client:
        login(client)
        created = client.post(
            "/api/uploads",
            json={"filename": "scene.blend", "size_bytes": 5},
        ).json()
        upload_id = created["id"]
        assert client.patch(
            f"/api/uploads/{upload_id}",
            content=b"bl",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "0"},
        ).status_code == 200

    restarted = create_app(settings, start_worker=False)
    with TestClient(restarted) as client:
        login(client)
        status = client.get(f"/api/uploads/{upload_id}")
        assert status.status_code == 200
        assert status.json()["uploaded_bytes"] == 2


def test_invalid_project_archive_remains_a_failed_upload(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        created = client.post(
            "/api/uploads",
            json={"filename": "project.zip", "size_bytes": 7},
        ).json()
        assert client.patch(
            f"/api/uploads/{created['id']}",
            content=b"not-zip",
            headers={"Content-Type": "application/octet-stream", "Upload-Offset": "0"},
        ).status_code == 200
        assert client.post(f"/api/uploads/{created['id']}/complete").status_code == 202
        for _ in range(100):
            upload = client.get(f"/api/uploads/{created['id']}").json()
            if upload["status"] == "failed":
                assert "invalid" in upload["error"].lower()
                break
            time.sleep(0.01)
        else:
            raise AssertionError("invalid archive did not fail")
        assert client.get("/api/scenes").json() == []


def test_foreign_job_is_read_only_and_results_are_grouped(settings, tmp_path) -> None:
    store = WorkspaceStore(settings)
    store.initialize()
    scene_id = "00000000-0000-4000-8000-000000000101"
    staging = store.staging_path(scene_id)
    (staging / "source").mkdir(parents=True)
    (staging / "source/input.blend").write_bytes(b"blend")
    store.create_scene(
        SceneManifest(
            id=scene_id,
            filename="input.blend",
            source_kind="blend",
            entrypoint="input.blend",
            created_at=utc_now(),
            size_bytes=5,
        ),
        staging,
    )
    job_id = "00000000-0000-4000-8000-000000000102"
    store.create_job(
        JobManifest(
            id=job_id,
            scene_id=scene_id,
            filename="input.blend",
            owner_pod_id="pod-b",
            mode="still",
            frame_start=2,
            frame_end=2,
            backend=Backend.CPU,
            created_at=utc_now(),
        )
    )
    for suffix in ("103", "104"):
        result_id = f"00000000-0000-4000-8000-000000000{suffix}"
        pending = store.job_paths(job_id)["pending"] / result_id
        pending.mkdir(parents=True)
        Image.new("RGB", (8, 8), (10, 20, 30)).save(pending / "frame.png", "PNG")
        Image.new("RGB", (8, 8), (10, 20, 30)).save(pending / "preview.webp", "WEBP")
        store.publish_result(
            FrameResult(
                id=result_id,
                scene_id=scene_id,
                job_id=job_id,
                frame=2,
                pod_id="pod-b",
                backend=Backend.CPU,
                hardware=["CPU"],
                samples=16,
                render_seconds=1.2,
                completed_at=utc_now(),
            ),
            pending,
        )
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        assert client.post(f"/api/jobs/{job_id}/cancel", json={}).status_code == 409
        frames = client.get(f"/api/scenes/{scene_id}/frames").json()
        assert len(frames["items"]) == 1
        assert len(frames["items"][0]["results"]) == 2
        image = client.get(
            f"/api/scenes/{scene_id}/results/00000000-0000-4000-8000-000000000103/image"
        )
        assert image.status_code == 200
        prepared = client.post(f"/api/scenes/{scene_id}/archive", json={"result_ids": None})
        assert prepared.status_code == 200
        download_url = prepared.json()["download_url"]
        archive = client.get(download_url)
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"
        assert 'filename="input-results.zip"' in archive.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert sorted(bundle.namelist()) == [
                "frame_000002-00000000-0000-4000-8000-000000000103.json",
                "frame_000002-00000000-0000-4000-8000-000000000103.png",
                "frame_000002-00000000-0000-4000-8000-000000000104.json",
                "frame_000002-00000000-0000-4000-8000-000000000104.png",
            ]
        assert client.get(download_url).status_code == 404


def test_scene_delete_rejects_active_jobs_and_job_delete_preserves_results(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        scene = upload_scene(client)
        job = client.post(
            "/api/jobs",
            json={"scene_id": scene["id"], "mode": "still", "frame": 1, "backend": "CPU"},
        ).json()
        assert client.delete(f"/api/scenes/{scene['id']}").status_code == 409
        assert client.post(f"/api/jobs/{job['id']}/cancel", json={}).status_code == 200
        store = WorkspaceStore(settings)
        pending = store.job_paths(job["id"])["pending"] / "00000000-0000-4000-8000-000000000199"
        pending.mkdir()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(pending / "frame.png", "PNG")
        Image.new("RGB", (8, 8), (10, 20, 30)).save(pending / "preview.webp", "WEBP")
        store.publish_result(
            FrameResult(
                id="00000000-0000-4000-8000-000000000199",
                scene_id=scene["id"],
                job_id=job["id"],
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
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
        frames = client.get(f"/api/scenes/{scene['id']}/frames").json()
        assert frames["items"][0]["results"][0]["job_id"] == job["id"]
