from __future__ import annotations

import io
import zipfile

from blendqueue.main import create_app
from blendqueue.worker import frame_filename, job_paths
from fastapi.testclient import TestClient
from PIL import Image


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "test-password"})
    assert response.status_code == 200


def create_job(client: TestClient, *, filename: str = "scene.blend"):
    return client.post(
        "/api/jobs",
        files={"file": (filename, b"BLENDER-v1-test-data", "application/octet-stream")},
        data={"mode": "range", "backend": "OPTIX", "start": "1", "end": "3"},
    )


def test_authentication_and_job_lifecycle(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        login(client)
        response = create_job(client)
        assert response.status_code == 201
        job = response.json()
        assert job["status"] == "queued"
        assert job["frame_start"] == 1
        canceled = client.post(f"/api/jobs/{job['id']}/cancel", json={})
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        retried = client.post(f"/api/jobs/{job['id']}/retry", json={})
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"


def test_cross_origin_mutation_is_rejected(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://malicious.example"},
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "Cross-origin request rejected"}
        assert response.headers["x-frame-options"] == "DENY"


def test_upload_validation(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        assert create_job(client, filename="scene.zip").status_code == 422
        response = client.post(
            "/api/jobs",
            files={"file": ("scene.blend", b"", "application/octet-stream")},
            data={"mode": "still", "backend": "CUDA", "frame": "4"},
        )
        assert response.status_code == 422


def test_frame_and_archive_download(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        job = create_job(client).json()
        paths = job_paths(settings, job["id"])
        paths["outputs"].mkdir(parents=True)
        for frame in (1, 2):
            Image.new("RGB", (8, 8), (frame * 20, 10, 5)).save(
                paths["outputs"] / frame_filename(frame), "PNG"
            )
        frame_response = client.get(f"/api/jobs/{job['id']}/frames/1")
        assert frame_response.status_code == 200
        assert frame_response.headers["content-type"] == "image/png"
        archive_response = client.post(
            f"/api/jobs/{job['id']}/archive", json={"frames": [1, 2]}
        )
        assert archive_response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
            assert archive.namelist() == [frame_filename(1), frame_filename(2)]
