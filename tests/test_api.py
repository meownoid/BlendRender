from __future__ import annotations

import io
import zipfile

from blendrender.main import create_app
from blendrender.worker import frame_filename, job_paths
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
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["status"] == "queued"
        assert job["frame_start"] == 1
        assert job["samples"] is None
        assert job["sample_current"] is None
        assert job["sample_total"] is None
        assert job["resolution_x"] is None
        assert job["resolution_y"] is None
        assert job["resolution_percentage"] is None
        canceled = client.post(f"/api/jobs/{job['id']}/cancel", json={})
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        retried = client.post(f"/api/jobs/{job['id']}/retry", json={})
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"


def test_system_info_exposes_host_telemetry(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        response = client.get("/api/system")
        assert response.status_code == 200
        system = response.json()
        assert 0 <= system["cpu_utilization"] <= 100
        assert 0 <= system["memory_used_bytes"] <= system["memory_total_bytes"]


def test_system_telemetry_is_authenticated_and_persisted(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/system/telemetry").status_code == 401
        login(client)
        response = client.get("/api/system/telemetry")
        assert response.status_code == 200
        samples = response.json()
        assert len(samples) == 1
        assert set(samples[0]) == {
            "captured_at",
            "cpu_utilization",
            "gpu_utilization",
            "memory_used_bytes",
            "memory_total_bytes",
            "vram_used_mb",
            "vram_total_mb",
        }
        captured_at = samples[0]["captured_at"]

    restarted = create_app(settings, start_worker=False)
    with TestClient(restarted) as client:
        login(client)
        samples = client.get("/api/system/telemetry").json()
        assert any(sample["captured_at"] == captured_at for sample in samples)


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


def test_cpu_backend_and_optional_render_overrides(settings) -> None:
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        login(client)
        response = client.post(
            "/api/jobs",
            files={"file": ("scene.blend", b"BLENDER-v1-test-data")},
            data={
                "mode": "still",
                "backend": "CPU",
                "frame": "8",
                "samples": "16",
                "resolution_x": "640",
                "resolution_y": "360",
                "resolution_percentage": "50",
            },
        )
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["backend"] == "CPU"
        assert job["samples"] == 16
        assert job["resolution_x"] == 640
        assert job["resolution_y"] == 360
        assert job["resolution_percentage"] == 50

        invalid_resolution = client.post(
            "/api/jobs",
            files={"file": ("scene.blend", b"BLENDER-v1-test-data")},
            data={
                "mode": "still",
                "backend": "CPU",
                "frame": "8",
                "resolution_x": "640",
            },
        )
        assert invalid_resolution.status_code == 422
        assert "provided together" in invalid_resolution.json()["detail"]


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
