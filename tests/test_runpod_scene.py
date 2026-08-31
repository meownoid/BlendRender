from __future__ import annotations

import logging
import zipfile
from pathlib import Path, PurePosixPath
from threading import Lock

import blendrender.runpod_scene as runpod_scene
import pytest
from blendrender.runpod_scene import (
    Boto3Uploader,
    ClearedVolume,
    PreparedScene,
    RunpodS3Settings,
    RunpodScenePreparationError,
    prepare_scene,
)
from botocore.config import Config
from botocore.exceptions import ClientError


class RecordingUploader:
    def __init__(self, existing: dict[PurePosixPath, int] | None = None) -> None:
        self.existing = existing or {}
        self.checked: list[PurePosixPath] = []
        self.uploads: list[tuple[str, PurePosixPath, bytes | dict[str, object]]] = []
        self.volume_checked = False

    def ensure_volume(self) -> None:
        self.volume_checked = True

    def object_exists(self, key: PurePosixPath) -> bool:
        self.checked.append(key)
        return key in self.existing

    def list_object_sizes(self, prefix: PurePosixPath) -> dict[PurePosixPath, int]:
        return {key: size for key, size in self.existing.items() if key.is_relative_to(prefix)}

    def upload_file(self, source: Path, key: PurePosixPath) -> None:
        self.uploads.append(("file", key, source.read_bytes()))

    def upload_json(self, payload: dict[str, object], key: PurePosixPath) -> None:
        self.uploads.append(("json", key, payload))


class RecordingS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.multipart: dict[str, dict[int, bytes]] = {}
        self.operations: list[str] = []
        self._lock = Lock()

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> dict[str, object]:
        self.operations.append("abort")
        self.multipart.pop(UploadId, None)
        return {}

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, object],
    ) -> dict[str, object]:
        self.operations.append("complete")
        parts = self.multipart[UploadId]
        self.objects[Key] = b"".join(parts[part] for part in sorted(parts))
        return {}

    def create_multipart_upload(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.operations.append("create")
        self.multipart["upload-1"] = {}
        return {"UploadId": "upload-1"}

    def head_bucket(self, *, Bucket: str) -> dict[str, object]:
        return {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        return {"ContentLength": len(self.objects[Key])}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int) -> dict[str, object]:
        return {"Contents": []}

    def put_object(
        self, *, Bucket: str, Key: str, Body: object, **kwargs: object
    ) -> dict[str, object]:
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()  # type: ignore[union-attr]
        return {}

    def upload_part(
        self, *, Bucket: str, Key: str, PartNumber: int, UploadId: str, Body: bytes
    ) -> dict[str, object]:
        with self._lock:
            self.operations.append(f"part-{PartNumber}")
            self.multipart[UploadId][PartNumber] = Body
        return {"ETag": f"etag-{PartNumber}"}


class ClearingS3Client:
    def __init__(self) -> None:
        self.objects = {"blendrender/a": b"a", "blendrender/b": b"b", "other": b"c"}
        self.aborted_uploads: list[tuple[str, str]] = []
        self.deleted_keys: list[str] = []

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> dict[str, object]:
        self.aborted_uploads.append((Key, UploadId))
        return {}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.deleted_keys.append(Key)
        self.objects.pop(Key, None)
        return {}

    def head_bucket(self, *, Bucket: str) -> dict[str, object]:
        return {}

    def list_multipart_uploads(self, *, Bucket: str, **options: object) -> dict[str, object]:
        key_marker = options.get("KeyMarker")
        upload_id_marker = options.get("UploadIdMarker")
        if key_marker is None and upload_id_marker is None:
            return {
                "Uploads": [{"Key": "blendrender/stalled-1", "UploadId": "upload-1"}],
                "IsTruncated": True,
                "NextKeyMarker": "blendrender/stalled-1",
                "NextUploadIdMarker": "upload-1",
            }
        assert key_marker == "blendrender/stalled-1"
        assert upload_id_marker == "upload-1"
        return {"Uploads": [{"Key": "blendrender/stalled-2", "UploadId": "upload-2"}]}

    def list_objects_v2(self, *, Bucket: str, **options: object) -> dict[str, object]:
        continuation_token = options.get("ContinuationToken")
        if continuation_token is None:
            return {
                "Contents": [{"Key": "blendrender/a"}, {"Key": "blendrender/b"}],
                "IsTruncated": True,
                "NextContinuationToken": "second-page",
            }
        assert continuation_token == "second-page"
        return {"Contents": [{"Key": "other"}]}


class CompletingAfterTimeoutS3Client:
    def __init__(self, expected_size: int) -> None:
        self.expected_size = expected_size
        self.complete_calls = 0

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, object],
    ) -> dict[str, object]:
        self.complete_calls += 1
        raise ClientError(
            {
                "Error": {"Code": "524", "Message": "Timed out"},
                "ResponseMetadata": {"HTTPStatusCode": 524},
            },
            "CompleteMultipartUpload",
        )

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        return {"ContentLength": self.expected_size}


class PaginatedObjectListingS3Client:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def list_objects_v2(self, *, Bucket: str, **options: object) -> dict[str, object]:
        self.requests.append(options)
        if options.get("ContinuationToken") is None:
            return {
                "Contents": [{"Key": "blendrender/scenes/scene/source/a.blend", "Size": 5}],
                "IsTruncated": True,
                "NextContinuationToken": "second-page",
            }
        assert options["ContinuationToken"] == "second-page"
        return {
            "Contents": [{"Key": "blendrender/scenes/scene/source/texture.png", "Size": 3}]
        }


class InterruptedMultipartS3Client(RecordingS3Client):
    def upload_part(
        self, *, Bucket: str, Key: str, PartNumber: int, UploadId: str, Body: bytes
    ) -> dict[str, object]:
        raise KeyboardInterrupt


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


def test_prepare_blend_uploads_source_before_publishing_scene_manifest(
    tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "hero.blend"
    source.write_bytes(b"blend")
    uploader = RecordingUploader()

    prepared = prepare_scene(
        source,
        runpod_settings,
        uploader,
        scene_id="00000000-0000-4000-8000-000000000401",
        scene_name="Hero scene",
    )

    assert prepared == PreparedScene(
        id="00000000-0000-4000-8000-000000000401",
        name="Hero scene",
        entrypoint="input.blend",
    )
    assert uploader.volume_checked
    assert [key for _, key, _ in uploader.uploads] == [
        PurePosixPath("blendrender/workspace.json"),
        PurePosixPath("blendrender/scenes/00000000-0000-4000-8000-000000000401/source/input.blend"),
        PurePosixPath("blendrender/scenes/00000000-0000-4000-8000-000000000401/manifest.json"),
    ]
    manifest = uploader.uploads[-1][2]
    assert isinstance(manifest, dict)
    assert manifest == {
        "schema_version": 2,
        "id": "00000000-0000-4000-8000-000000000401",
        "filename": "input.blend",
        "name": "Hero scene",
        "source_kind": "blend",
        "entrypoint": "input.blend",
        "created_at": manifest["created_at"],
        "size_bytes": 5,
        "job_count": 0,
        "result_count": 0,
    }


def test_prepare_zip_extracts_and_uploads_the_project_tree(
    tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "hero.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("project/scenes/main.blend", b"blend")
        archive.writestr("project/textures/sky.png", b"png")
    uploader = RecordingUploader({PurePosixPath("blendrender/workspace.json"): 1})

    prepared = prepare_scene(
        source,
        runpod_settings,
        uploader,
        scene_id="00000000-0000-4000-8000-000000000402",
    )

    assert prepared.entrypoint == "project/scenes/main.blend"
    assert [key for _, key, _ in uploader.uploads] == [
        PurePosixPath(
            "blendrender/scenes/00000000-0000-4000-8000-000000000402/source/project/scenes/main.blend"
        ),
        PurePosixPath(
            "blendrender/scenes/00000000-0000-4000-8000-000000000402/source/project/textures/sky.png"
        ),
        PurePosixPath("blendrender/scenes/00000000-0000-4000-8000-000000000402/manifest.json"),
    ]
    manifest = uploader.uploads[-1][2]
    assert isinstance(manifest, dict)
    assert manifest["source_kind"] == "zip"
    assert manifest["entrypoint"] == "project/scenes/main.blend"


def test_prepare_scene_does_not_overwrite_an_existing_scene(
    tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "hero.blend"
    source.write_bytes(b"blend")
    scene_id = "00000000-0000-4000-8000-000000000403"
    uploader = RecordingUploader(
        {PurePosixPath(f"blendrender/scenes/{scene_id}/manifest.json"): 1}
    )

    with pytest.raises(RunpodScenePreparationError, match="already complete"):
        prepare_scene(source, runpod_settings, uploader, scene_id=scene_id)

    assert uploader.uploads == []


def test_prepare_scene_resumes_and_skips_matching_existing_files(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    runpod_settings: RunpodS3Settings,
) -> None:
    source = tmp_path / "hero.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("project/scenes/main.blend", b"blend")
        archive.writestr("project/textures/sky.png", b"png")
    scene_id = "00000000-0000-4000-8000-000000000404"
    existing_file = PurePosixPath(
        f"blendrender/scenes/{scene_id}/source/project/scenes/main.blend"
    )
    uploader = RecordingUploader(
        {
            PurePosixPath("blendrender/workspace.json"): 1,
            existing_file: 5,
        }
    )
    caplog.set_level(logging.INFO, logger=runpod_scene.__name__)

    prepared = prepare_scene(source, runpod_settings, uploader, scene_id=scene_id)

    assert prepared.entrypoint == "project/scenes/main.blend"
    assert [key for _, key, _ in uploader.uploads] == [
        PurePosixPath(
            f"blendrender/scenes/{scene_id}/source/project/textures/sky.png"
        ),
        PurePosixPath(f"blendrender/scenes/{scene_id}/manifest.json"),
    ]
    assert f"Skipping already uploaded {existing_file} (5 bytes)" in caplog.messages


def test_prepare_scene_refuses_to_resume_when_an_existing_file_has_a_different_size(
    tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "hero.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("project/scenes/main.blend", b"blend")
        archive.writestr("project/textures/sky.png", b"png")
    scene_id = "00000000-0000-4000-8000-000000000405"
    uploader = RecordingUploader(
        {
            PurePosixPath("blendrender/workspace.json"): 1,
            PurePosixPath(
                f"blendrender/scenes/{scene_id}/source/project/textures/sky.png"
            ): 4,
        }
    )

    with pytest.raises(RunpodScenePreparationError, match="current input has size 3"):
        prepare_scene(source, runpod_settings, uploader, scene_id=scene_id)

    assert uploader.uploads == []


def test_prepare_scene_refuses_to_resume_with_unexpected_existing_files(
    tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "hero.blend"
    source.write_bytes(b"blend")
    scene_id = "00000000-0000-4000-8000-000000000406"
    unexpected = PurePosixPath(f"blendrender/scenes/{scene_id}/source/old.blend")
    uploader = RecordingUploader(
        {
            PurePosixPath("blendrender/workspace.json"): 1,
            unexpected: 5,
        }
    )

    with pytest.raises(
        RunpodScenePreparationError, match=f"unexpected existing object {unexpected}"
    ):
        prepare_scene(source, runpod_settings, uploader, scene_id=scene_id)

    assert uploader.uploads == []


def test_boto3_uploader_completes_and_verifies_a_large_multipart_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "large.blend"
    source.write_bytes(b"abcdefg")
    client = RecordingS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(runpod_scene, "MULTIPART_THRESHOLD_BYTES", 3)
    monkeypatch.setattr(runpod_scene, "MULTIPART_PART_SIZE_BYTES", 3)
    monkeypatch.setattr(uploader, "_client", client)
    monkeypatch.setattr(uploader, "_new_client", lambda _: client)

    uploader.upload_file(source, PurePosixPath("blendrender/scenes/large/source/input.blend"))

    assert client.objects["blendrender/scenes/large/source/input.blend"] == b"abcdefg"
    assert client.operations[0] == "create"
    assert client.operations[-1] == "complete"


def test_boto3_uploader_logs_direct_file_uploads(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runpod_settings: RunpodS3Settings,
) -> None:
    source = tmp_path / "small.blend"
    source.write_bytes(b"blend")
    client = RecordingS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(uploader, "_client", client)
    caplog.set_level(logging.INFO, logger=runpod_scene.__name__)

    uploader.upload_file(source, PurePosixPath("blendrender/scenes/small/source/input.blend"))

    assert (
        "Uploading blendrender/scenes/small/source/input.blend directly (0.0 MiB)"
        in caplog.messages
    )
    assert "Uploaded blendrender/scenes/small/source/input.blend" in caplog.messages


def test_boto3_uploader_lists_all_existing_object_sizes(
    monkeypatch: pytest.MonkeyPatch, runpod_settings: RunpodS3Settings
) -> None:
    client = PaginatedObjectListingS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(uploader, "_client", client)

    sizes = uploader.list_object_sizes(PurePosixPath("blendrender/scenes/scene"))

    assert sizes == {
        PurePosixPath("blendrender/scenes/scene/source/a.blend"): 5,
        PurePosixPath("blendrender/scenes/scene/source/texture.png"): 3,
    }
    assert client.requests == [
        {"Prefix": "blendrender/scenes/scene/", "MaxKeys": 1000},
        {
            "Prefix": "blendrender/scenes/scene/",
            "MaxKeys": 1000,
            "ContinuationToken": "second-page",
        },
    ]


def test_boto3_uploader_recovers_a_timed_out_multipart_completion(
    monkeypatch: pytest.MonkeyPatch, runpod_settings: RunpodS3Settings
) -> None:
    client = CompletingAfterTimeoutS3Client(expected_size=7)
    uploader = Boto3Uploader(runpod_settings)
    configs: list[Config] = []

    def new_client(config: Config) -> CompletingAfterTimeoutS3Client:
        configs.append(config)
        return client

    monkeypatch.setattr(uploader, "_new_client", new_client)
    monkeypatch.setattr(runpod_scene.time, "sleep", lambda _: None)

    uploader._complete_multipart_upload(
        PurePosixPath("blendrender/scenes/large/source/input.blend"),
        "upload-1",
        [{"PartNumber": 1, "ETag": "etag-1"}],
        expected_size=7,
    )

    assert client.complete_calls == 1
    assert configs[0].retries["total_max_attempts"] == 1


def test_boto3_uploader_disables_automatic_boto_retries(
    runpod_settings: RunpodS3Settings,
) -> None:
    uploader = Boto3Uploader(runpod_settings)

    assert uploader._config.retries["total_max_attempts"] == 1


def test_boto3_uploader_logs_each_explicit_retry(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    runpod_settings: RunpodS3Settings,
) -> None:
    uploader = Boto3Uploader(runpod_settings)
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ClientError(
                {
                    "Error": {"Code": "502", "Message": "Bad gateway"},
                    "ResponseMetadata": {"HTTPStatusCode": 502},
                },
                "PutObject",
            )
        return "uploaded"

    caplog.set_level(logging.INFO, logger=runpod_scene.__name__)
    monkeypatch.setattr(runpod_scene.time, "sleep", lambda _: None)

    assert uploader._request_with_retry("upload input.blend", operation) == "uploaded"
    assert attempts == 3
    assert "upload input.blend: retrying attempt 2/5 in 2 seconds" in caplog.messages
    assert "upload input.blend: retrying attempt 3/5 in 4 seconds" in caplog.messages


def test_boto3_uploader_aborts_a_multipart_upload_when_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runpod_settings: RunpodS3Settings
) -> None:
    source = tmp_path / "large.blend"
    source.write_bytes(b"abcdefg")
    client = InterruptedMultipartS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(runpod_scene, "MULTIPART_THRESHOLD_BYTES", 3)
    monkeypatch.setattr(runpod_scene, "MULTIPART_PART_SIZE_BYTES", 3)
    monkeypatch.setattr(uploader, "_client", client)
    monkeypatch.setattr(uploader, "_new_client", lambda _: client)

    with pytest.raises(KeyboardInterrupt):
        uploader.upload_file(source, PurePosixPath("blendrender/scenes/large/source/input.blend"))

    assert client.operations == ["create", "abort"]


def test_boto3_uploader_clears_all_objects_and_incomplete_multipart_uploads(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    runpod_settings: RunpodS3Settings,
) -> None:
    client = ClearingS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(uploader, "_client", client)
    caplog.set_level(logging.INFO, logger=runpod_scene.__name__)

    cleared = uploader.clear_volume(dry_run=False)

    assert cleared == ClearedVolume(
        deleted_object_count=3,
        aborted_multipart_upload_count=2,
        dry_run=False,
    )
    assert client.objects == {}
    assert client.deleted_keys == ["blendrender/a", "blendrender/b", "other"]
    assert client.aborted_uploads == [
        ("blendrender/stalled-1", "upload-1"),
        ("blendrender/stalled-2", "upload-2"),
    ]
    assert "Found 2 incomplete multipart uploads" in caplog.messages
    assert "Deleting object blendrender/a" in caplog.messages
    assert "Deleted 3 network-volume objects" in caplog.messages


def test_boto3_uploader_cleanup_dry_run_does_not_change_the_network_volume(
    monkeypatch: pytest.MonkeyPatch, runpod_settings: RunpodS3Settings
) -> None:
    client = ClearingS3Client()
    uploader = Boto3Uploader(runpod_settings)
    monkeypatch.setattr(uploader, "_client", client)

    cleared = uploader.clear_volume(dry_run=True)

    assert cleared == ClearedVolume(
        deleted_object_count=3,
        aborted_multipart_upload_count=2,
        dry_run=True,
    )
    assert client.objects == {"blendrender/a": b"a", "blendrender/b": b"b", "other": b"c"}
    assert client.deleted_keys == []
    assert client.aborted_uploads == []


def test_runpod_settings_use_the_default_datacenter_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "user_test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "rps_test")
    monkeypatch.setenv("RUNPOD_NETWORK_VOLUME_ID", "network-volume-id")
    monkeypatch.setenv("RUNPOD_S3_REGION", "EUR-IS-1")
    monkeypatch.delenv("RUNPOD_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    settings = RunpodS3Settings.from_env()

    assert settings.endpoint_url == "https://s3api-eur-is-1.runpod.io/"
    assert settings.workspace_prefix == PurePosixPath("blendrender")
