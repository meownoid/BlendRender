from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
from blendrender.runpod_catalog import (
    DeletionSummary,
    delete_jobs,
    delete_results,
    delete_scenes,
    download_results,
    list_scenes,
)
from blendrender.runpod_scene import RunpodS3Settings, RunpodScenePreparationError


class CatalogUploader:
    upload_workers = 2

    def __init__(self, objects: dict[PurePosixPath, bytes]) -> None:
        self.objects = objects
        self.volume_checked = False
        self.downloaded_keys: list[PurePosixPath] = []
        self.deleted_keys: list[PurePosixPath] = []

    def ensure_volume(self) -> None:
        self.volume_checked = True

    def object_exists(self, key: PurePosixPath) -> bool:
        return key in self.objects

    def list_object_sizes(self, prefix: PurePosixPath) -> dict[PurePosixPath, int]:
        return {
            key: len(content)
            for key, content in self.objects.items()
            if key.is_relative_to(prefix)
        }

    def read_json(self, key: PurePosixPath) -> dict[str, object]:
        return json.loads(self.objects[key])  # type: ignore[no-any-return]

    def download_file(self, key: PurePosixPath, destination: Path) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(self.objects[key])
        self.downloaded_keys.append(key)
        return len(self.objects[key])

    def delete_objects(self, keys: tuple[PurePosixPath, ...]) -> None:
        self.deleted_keys.extend(keys)
        for key in keys:
            del self.objects[key]

    def upload_file(self, source: Path, key: PurePosixPath) -> None:
        raise NotImplementedError

    def upload_json(self, payload: dict[str, object], key: PurePosixPath) -> None:
        raise NotImplementedError


@pytest.fixture
def runpod_settings() -> RunpodS3Settings:
    return RunpodS3Settings(
        access_key_id="user_test",
        secret_access_key="rps_test",
        volume_id="network-volume-id",
        region="EUR-IS-1",
        endpoint_url="https://s3api-eur-is-1.runpod.io/",
        workspace_prefix=PurePosixPath("blendrender"),
        max_upload_bytes=1024 * 1024,
    )


@pytest.fixture
def catalog_uploader() -> CatalogUploader:
    scene_a = "00000000-0000-4000-8000-000000000501"
    scene_b = "00000000-0000-4000-8000-000000000502"
    job_id = "00000000-0000-4000-8000-000000000503"
    result_id = "00000000-0000-4000-8000-000000000504"
    scene_a_root = PurePosixPath(f"blendrender/scenes/{scene_a}")
    scene_b_root = PurePosixPath(f"blendrender/scenes/{scene_b}")
    job_root = PurePosixPath(f"blendrender/jobs/{job_id}")
    result_root = scene_a_root / "results/000001" / result_id
    objects = {
        scene_a_root / "manifest.json": _json(
            {
                "schema_version": 2,
                "id": scene_a,
                "filename": "a.blend",
                "name": "Scene A",
                "source_kind": "zip",
                "entrypoint": "project/a.blend",
                "created_at": "2026-01-01T00:00:00+00:00",
                "size_bytes": 10,
            }
        ),
        scene_b_root / "manifest.json": _json(
            {
                "schema_version": 2,
                "id": scene_b,
                "filename": "b.blend",
                "name": "Scene B",
                "source_kind": "blend",
                "entrypoint": "input.blend",
                "created_at": "2026-01-02T00:00:00+00:00",
                "size_bytes": 20,
            }
        ),
        job_root / "manifest.json": _json(
            {
                "schema_version": 2,
                "id": job_id,
                "scene_id": scene_a,
                "filename": "a.blend",
                "owner_pod_id": "pod-a",
                "mode": "still",
                "frame_start": 1,
                "frame_end": 1,
                "backend": "OPTIX",
                "created_at": "2026-01-03T00:00:00+00:00",
            }
        ),
        job_root / "status.json": _json(
            {
                "schema_version": 2,
                "status": "completed",
                "progress": 100,
                "updated_at": "2026-01-03T00:01:00+00:00",
            }
        ),
        result_root / "metadata.json": _json(
            {
                "schema_version": 2,
                "id": result_id,
                "scene_id": scene_a,
                "job_id": job_id,
                "frame": 1,
                "pod_id": "pod-a",
                "backend": "OPTIX",
                "samples": 64,
                "render_seconds": 1.5,
                "completed_at": "2026-01-03T00:01:00+00:00",
            }
        ),
        result_root / "frame.png": b"png",
        result_root / "preview.webp": b"preview",
    }
    return CatalogUploader(objects)


def test_list_scenes_groups_jobs_and_result_packages(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scenes = list_scenes(catalog_uploader, runpod_settings)

    assert catalog_uploader.volume_checked
    assert [scene.manifest.name for scene in scenes] == ["Scene B", "Scene A"]
    scene_a = scenes[1]
    assert scene_a.jobs[0].manifest.owner_pod_id == "pod-a"
    assert scene_a.jobs[0].status is not None
    assert scene_a.jobs[0].status.status.value == "completed"
    assert scene_a.results[0].result.frame == 1
    assert [file.key.name for file in scene_a.results[0].files] == [
        "frame.png",
        "metadata.json",
        "preview.webp",
    ]


def test_list_scenes_filters_to_one_scene_and_rejects_unknown_ids(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scene_id = "00000000-0000-4000-8000-000000000501"

    scenes = list_scenes(catalog_uploader, runpod_settings, scene_id=scene_id)

    assert [scene.manifest.id for scene in scenes] == [scene_id]
    with pytest.raises(RunpodScenePreparationError, match="was not found"):
        list_scenes(catalog_uploader, runpod_settings, scene_id="not-a-scene")


def test_download_results_writes_only_selected_scene_result_packages(
    tmp_path: Path, catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scene_id = "00000000-0000-4000-8000-000000000501"
    scenes = list_scenes(catalog_uploader, runpod_settings, scene_id=scene_id)

    summary = download_results(catalog_uploader, runpod_settings, scenes, tmp_path / "results")

    destination = (
        tmp_path
        / "results"
        / "scenes"
        / scene_id
        / "results"
        / "000001"
        / "00000000-0000-4000-8000-000000000504"
    )
    assert summary.file_count == 3
    metadata_key = next(key for key in catalog_uploader.objects if key.name == "metadata.json")
    expected_size = len(b"png") + len(b"preview") + len(catalog_uploader.objects[metadata_key])
    assert summary.size_bytes == expected_size
    assert (destination / "frame.png").read_bytes() == b"png"
    assert (destination / "preview.webp").read_bytes() == b"preview"
    assert all(scene_id in key.as_posix() for key in catalog_uploader.downloaded_keys)


def test_download_results_refuses_a_non_empty_destination(
    tmp_path: Path, catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    destination = tmp_path / "results"
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")
    scenes = list_scenes(catalog_uploader, runpod_settings)

    with pytest.raises(RunpodScenePreparationError, match="non-empty directory"):
        download_results(catalog_uploader, runpod_settings, scenes, destination)


def test_download_results_refuses_a_file_destination(
    tmp_path: Path, catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    destination = tmp_path / "results.txt"
    destination.write_text("keep", encoding="utf-8")
    scenes = list_scenes(catalog_uploader, runpod_settings)

    with pytest.raises(RunpodScenePreparationError, match="is not a directory"):
        download_results(catalog_uploader, runpod_settings, scenes, destination)


def test_delete_scene_removes_its_results_and_terminal_jobs(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scene_id = "00000000-0000-4000-8000-000000000501"
    scenes = list_scenes(catalog_uploader, runpod_settings)

    summary = delete_scenes(
        catalog_uploader,
        runpod_settings,
        scenes,
        scene_ids=frozenset({scene_id}),
    )

    assert summary == DeletionSummary(entity_kind="scene", entity_count=1, object_count=6)
    assert all(scene_id not in key.as_posix() for key in catalog_uploader.objects)
    assert all(
        "00000000-0000-4000-8000-000000000503" not in key.as_posix()
        for key in catalog_uploader.objects
    )
    assert (
        PurePosixPath(f"blendrender/scenes/{scene_id}/manifest.json")
        in catalog_uploader.deleted_keys
    )


def test_delete_job_preserves_its_published_results(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    job_id = "00000000-0000-4000-8000-000000000503"
    scenes = list_scenes(catalog_uploader, runpod_settings)

    summary = delete_jobs(
        catalog_uploader,
        runpod_settings,
        scenes,
        job_ids=frozenset({job_id}),
    )

    assert summary == DeletionSummary(entity_kind="job", entity_count=1, object_count=2)
    assert all(job_id not in key.as_posix() for key in catalog_uploader.objects)
    assert any("results" in key.parts for key in catalog_uploader.objects)


def test_delete_result_preserves_its_scene_and_job(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scene_id = "00000000-0000-4000-8000-000000000501"
    result_id = "00000000-0000-4000-8000-000000000504"
    scenes = list_scenes(catalog_uploader, runpod_settings)

    summary = delete_results(catalog_uploader, scenes, result_ids=frozenset({result_id}))

    assert summary == DeletionSummary(entity_kind="result", entity_count=1, object_count=3)
    assert all(result_id not in key.as_posix() for key in catalog_uploader.objects)
    assert PurePosixPath(f"blendrender/scenes/{scene_id}/manifest.json") in catalog_uploader.objects
    assert any("jobs" in key.parts for key in catalog_uploader.objects)


def test_delete_rejects_an_unknown_catalog_id(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    scenes = list_scenes(catalog_uploader, runpod_settings)

    with pytest.raises(RunpodScenePreparationError, match="Completed job not-a-job was not found"):
        delete_jobs(catalog_uploader, runpod_settings, scenes, job_ids=frozenset({"not-a-job"}))


def test_delete_job_refuses_a_queued_job(
    catalog_uploader: CatalogUploader, runpod_settings: RunpodS3Settings
) -> None:
    job_id = "00000000-0000-4000-8000-000000000503"
    status_key = PurePosixPath(f"blendrender/jobs/{job_id}/status.json")
    catalog_uploader.objects[status_key] = _json(
        {
            "schema_version": 2,
            "status": "queued",
            "progress": 0,
            "updated_at": "2026-01-03T00:01:00+00:00",
        }
    )
    scenes = list_scenes(catalog_uploader, runpod_settings)

    with pytest.raises(RunpodScenePreparationError, match=f"job {job_id} is queued"):
        delete_jobs(catalog_uploader, runpod_settings, scenes, job_ids=frozenset({job_id}))

    assert catalog_uploader.deleted_keys == []


def _json(value: dict[str, object]) -> bytes:
    return json.dumps(value).encode()
