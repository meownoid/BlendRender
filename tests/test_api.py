from __future__ import annotations

import io
import zipfile

from blendrender.main import create_app
from blendrender.models import Backend, FrameResult, JobManifest, SceneManifest, utc_now
from blendrender.workspace import WorkspaceStore
from fastapi.testclient import TestClient
from PIL import Image


def login(client: TestClient) -> None:
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200


def upload_scene(
    client: TestClient, filename: str = "scene.blend", content: bytes = b"blend"
) -> dict:
    response = client.post("/api/scenes", files={"file": (filename, content)})
    assert response.status_code == 201, response.text
    return response.json()


def test_scene_upload_then_local_job_creation(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        scene = upload_scene(client)
        assert scene["filename"] == "input.blend"
        created = client.post(
            "/api/jobs",
            json={
                "scene_id": scene["id"],
                "mode": "range",
                "start": 1,
                "end": 3,
                "backend": "OPTIX",
            },
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["owner_pod_id"] == "pod-a"
        assert job["scene_id"] == scene["id"]
        assert client.get("/api/scenes").json()[0]["job_count"] == 1


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
        archive = client.post(f"/api/scenes/{scene_id}/archive", json={"result_ids": None})
        assert archive.status_code == 200


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
