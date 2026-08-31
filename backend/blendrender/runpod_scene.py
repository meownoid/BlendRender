"""Prepare an immutable BlendRender scene through RunPod's S3-compatible API."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any, Literal, Protocol, TypedDict, TypeVar, cast
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .models import SceneManifest, WorkspaceManifest, utc_now
from .project_archive import ProjectArchiveError, extract_project_archive, inspect_project_archive

MEBIBYTE = 1024**2
GIBIBYTE = 1024**3
MULTIPART_THRESHOLD_BYTES = 50 * MEBIBYTE
MULTIPART_PART_SIZE_BYTES = 50 * MEBIBYTE
MULTIPART_WORKERS = 4
S3_MAX_RETRIES = 5
S3_INITIAL_TIMEOUT_SECONDS = 60
S3_COMPLETE_POLL_SECONDS = 5
logger = logging.getLogger(__name__)
T = TypeVar("T")


class RunpodScenePreparationError(RuntimeError):
    """Raised when a scene cannot safely be prepared on a RunPod network volume."""


@dataclass(frozen=True, slots=True)
class RunpodS3Settings:
    """S3 connection details and the BlendRender path within a RunPod network volume."""

    access_key_id: str
    secret_access_key: str
    volume_id: str
    region: str
    endpoint_url: str
    workspace_prefix: PurePosixPath
    max_upload_bytes: int

    @classmethod
    def from_env(cls) -> RunpodS3Settings:
        access_key_id = _required_env("AWS_ACCESS_KEY_ID")
        secret_access_key = _required_env("AWS_SECRET_ACCESS_KEY")
        volume_id = _required_env("RUNPOD_NETWORK_VOLUME_ID")
        region = _required_env("RUNPOD_S3_REGION")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", volume_id):
            raise RunpodScenePreparationError(
                "RUNPOD_NETWORK_VOLUME_ID must be a network-volume ID, not a display name"
            )

        endpoint_url = os.getenv("RUNPOD_S3_ENDPOINT", "").strip()
        if not endpoint_url:
            endpoint_url = f"https://s3api-{region.lower()}.runpod.io/"
        _validate_endpoint(endpoint_url)
        return cls(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            volume_id=volume_id,
            region=region,
            endpoint_url=endpoint_url,
            workspace_prefix=_workspace_prefix_from_env(),
            max_upload_bytes=_max_upload_bytes_from_env(),
        )


class ObjectUploader(Protocol):
    def ensure_volume(self) -> None: ...

    def object_exists(self, key: PurePosixPath) -> bool: ...

    def list_object_sizes(self, prefix: PurePosixPath) -> dict[PurePosixPath, int]: ...

    def upload_file(self, source: Path, key: PurePosixPath) -> None: ...

    def upload_json(self, payload: dict[str, object], key: PurePosixPath) -> None: ...


class S3Client(Protocol):
    def abort_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str
    ) -> dict[str, Any]: ...

    def complete_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict[str, object]
    ) -> dict[str, Any]: ...

    def create_multipart_upload(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    def list_multipart_uploads(self, *, Bucket: str, **kwargs: object) -> dict[str, Any]: ...

    def list_objects_v2(self, *, Bucket: str, **kwargs: object) -> dict[str, Any]: ...

    def put_object(
        self, *, Bucket: str, Key: str, Body: object, **kwargs: object
    ) -> dict[str, Any]: ...

    def upload_part(
        self, *, Bucket: str, Key: str, PartNumber: int, UploadId: str, Body: bytes
    ) -> dict[str, Any]: ...


class MultipartPart(TypedDict):
    PartNumber: int
    ETag: str


@dataclass(frozen=True, slots=True)
class ClearedVolume:
    """The work performed by a network-volume cleanup operation."""

    deleted_object_count: int
    aborted_multipart_upload_count: int
    dry_run: bool


class Boto3Uploader:
    """Upload scene data through RunPod's S3 API with reliable large-file multipart transfers."""

    def __init__(self, settings: RunpodS3Settings) -> None:
        self.settings = settings
        self._session: Any = boto3.session.Session(
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name=settings.region,
        )
        self._config = Config(
            region_name=settings.region,
            connect_timeout=S3_INITIAL_TIMEOUT_SECONDS,
            read_timeout=S3_INITIAL_TIMEOUT_SECONDS,
            # Retries are explicit in _request_with_retry so each is visible in the terminal.
            retries={"total_max_attempts": 1, "mode": "standard"},
        )
        self._client = self._new_client(self._config)

    def ensure_volume(self) -> None:
        self._request(
            "verify network volume",
            lambda: self._client.head_bucket(Bucket=self.settings.volume_id),
        )

    def object_exists(self, key: PurePosixPath) -> bool:
        try:
            self._request_with_retry(
                "check object",
                lambda: self._client.head_object(
                    Bucket=self.settings.volume_id, Key=key.as_posix()
                ),
            )
        except ClientError as exc:
            if _is_not_found_error(exc):
                return False
            raise _s3_error("check object", exc) from exc
        except BotoCoreError as exc:
            raise _s3_error("check object", exc) from exc
        return True

    def list_object_sizes(self, prefix: PurePosixPath) -> dict[PurePosixPath, int]:
        sizes: dict[PurePosixPath, int] = {}
        continuation_token: str | None = None
        while True:
            options: dict[str, object] = {
                "Prefix": f"{prefix.as_posix()}/",
                "MaxKeys": 1000,
            }
            if continuation_token is not None:
                options["ContinuationToken"] = continuation_token

            def list_page(current_options: dict[str, object] = options) -> dict[str, Any]:
                return self._client.list_objects_v2(
                    Bucket=self.settings.volume_id,
                    **current_options,
                )

            response = self._request(
                f"list objects under {prefix}",
                list_page,
            )
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RunpodScenePreparationError("RunPod S3 returned an invalid object listing")
            for item in contents:
                key = PurePosixPath(_object_key(item))
                size = _object_size(item)
                sizes[key] = size

            if response.get("IsTruncated") is not True:
                return sizes
            next_token = response.get("NextContinuationToken")
            if not isinstance(next_token, str) or not next_token:
                raise RunpodScenePreparationError(
                    "RunPod S3 returned a truncated object listing without a continuation token"
                )
            continuation_token = next_token

    def upload_file(self, source: Path, key: PurePosixPath) -> None:
        size_bytes = source.stat().st_size
        if size_bytes >= MULTIPART_THRESHOLD_BYTES:
            self._upload_multipart(source, key, size_bytes)
        else:
            logger.info("Uploading %s directly (%.1f MiB)", key, size_bytes / MEBIBYTE)
            with source.open("rb") as content:
                def put_object() -> dict[str, Any]:
                    content.seek(0)
                    return self._client.put_object(
                        Bucket=self.settings.volume_id,
                        Key=key.as_posix(),
                        Body=content,
                    )

                self._request(
                    f"upload {key}",
                    put_object,
                )
            self._verify_object_size(key, size_bytes)
        logger.info("Uploaded %s", key)

    def upload_json(self, payload: dict[str, object], key: PurePosixPath) -> None:
        content = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
        logger.info("Uploading %s directly (JSON, %s bytes)", key, len(content))
        self._request(
            f"upload {key}",
            lambda: self._client.put_object(
                Bucket=self.settings.volume_id,
                Key=key.as_posix(),
                Body=content,
                ContentType="application/json",
            ),
        )
        self._verify_object_size(key, len(content))
        logger.info("Uploaded %s", key)

    def clear_volume(self, *, dry_run: bool) -> ClearedVolume:
        """Delete every object and incomplete multipart upload from the network volume."""

        logger.info("Verifying access to network volume %s", self.settings.volume_id)
        self.ensure_volume()
        logger.info("Listing incomplete multipart uploads")
        multipart_uploads = tuple(self._iter_multipart_uploads())
        logger.info("Found %s incomplete multipart uploads", len(multipart_uploads))
        if dry_run:
            logger.info("Dry run: counting network-volume objects")
            deleted_object_count = 0
            for _ in self._iter_object_keys():
                deleted_object_count += 1
                if deleted_object_count % 1000 == 0:
                    logger.info("Dry run: found %s objects", deleted_object_count)
            logger.info("Dry run: found %s objects", deleted_object_count)
            return ClearedVolume(
                deleted_object_count=deleted_object_count,
                aborted_multipart_upload_count=len(multipart_uploads),
                dry_run=True,
            )

        for position, (key, upload_id) in enumerate(multipart_uploads, start=1):
            def abort(current_key: str = key, current_upload_id: str = upload_id) -> dict[str, Any]:
                return self._client.abort_multipart_upload(
                    Bucket=self.settings.volume_id,
                    Key=current_key,
                    UploadId=current_upload_id,
                )

            logger.info(
                "Aborting incomplete multipart upload %s/%s for %s",
                position,
                len(multipart_uploads),
                key,
            )
            self._request(
                f"abort multipart upload for {key}",
                abort,
            )

        logger.info("Deleting network-volume objects")
        deleted_object_count = 0
        for key in self._iter_object_keys():
            def delete(current_key: str = key) -> dict[str, Any]:
                return self._client.delete_object(
                    Bucket=self.settings.volume_id,
                    Key=current_key,
                )

            logger.info("Deleting object %s", key)
            response = self._request(
                f"delete object {key}",
                delete,
            )
            if response.get("Errors"):
                raise RunpodScenePreparationError(f"RunPod S3 could not delete {key}")
            deleted_object_count += 1

        logger.info("Deleted %s network-volume objects", deleted_object_count)
        return ClearedVolume(
            deleted_object_count=deleted_object_count,
            aborted_multipart_upload_count=len(multipart_uploads),
            dry_run=False,
        )

    def _iter_object_key_batches(self) -> Iterator[tuple[str, ...]]:
        continuation_token: str | None = None
        while True:
            options: dict[str, object] = {"MaxKeys": 1000}
            if continuation_token is not None:
                options["ContinuationToken"] = continuation_token
            def list_page(current_options: dict[str, object] = options) -> dict[str, Any]:
                return self._client.list_objects_v2(
                    Bucket=self.settings.volume_id,
                    **current_options,
                )

            response = self._request(
                "list network-volume objects",
                list_page,
            )
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RunpodScenePreparationError("RunPod S3 returned an invalid object listing")
            keys = tuple(_object_key(item) for item in contents)
            if keys:
                yield keys

            if response.get("IsTruncated") is not True:
                return
            next_token = response.get("NextContinuationToken")
            if not isinstance(next_token, str) or not next_token:
                raise RunpodScenePreparationError(
                    "RunPod S3 returned a truncated object listing without a continuation token"
                )
            continuation_token = next_token

    def _iter_object_keys(self) -> Iterator[str]:
        for keys in self._iter_object_key_batches():
            yield from keys

    def _iter_multipart_uploads(self) -> Iterator[tuple[str, str]]:
        key_marker: str | None = None
        upload_id_marker: str | None = None
        while True:
            options: dict[str, object] = {}
            if key_marker is not None:
                options["KeyMarker"] = key_marker
            if upload_id_marker is not None:
                options["UploadIdMarker"] = upload_id_marker
            def list_page(current_options: dict[str, object] = options) -> dict[str, Any]:
                return self._client.list_multipart_uploads(
                    Bucket=self.settings.volume_id,
                    **current_options,
                )

            response = self._request(
                "list incomplete multipart uploads",
                list_page,
            )
            uploads = response.get("Uploads", [])
            if not isinstance(uploads, list):
                raise RunpodScenePreparationError(
                    "RunPod S3 returned an invalid multipart-upload listing"
                )
            for upload in uploads:
                if not isinstance(upload, dict):
                    raise RunpodScenePreparationError(
                        "RunPod S3 returned an invalid multipart-upload entry"
                    )
                key = upload.get("Key")
                upload_id = upload.get("UploadId")
                if (
                    not isinstance(key, str)
                    or not key
                    or not isinstance(upload_id, str)
                    or not upload_id
                ):
                    raise RunpodScenePreparationError(
                        "RunPod S3 returned an incomplete multipart-upload entry"
                    )
                yield key, upload_id

            if response.get("IsTruncated") is not True:
                return
            next_key_marker = response.get("NextKeyMarker")
            next_upload_id_marker = response.get("NextUploadIdMarker")
            if (
                not isinstance(next_key_marker, str)
                or not next_key_marker
                or not isinstance(next_upload_id_marker, str)
                or not next_upload_id_marker
            ):
                raise RunpodScenePreparationError(
                    "RunPod S3 returned a truncated multipart-upload listing without "
                    "continuation markers"
                )
            key_marker = next_key_marker
            upload_id_marker = next_upload_id_marker

    def _upload_multipart(self, source: Path, key: PurePosixPath, size_bytes: int) -> None:
        created = self._request(
            f"start multipart upload for {key}",
            lambda: self._client.create_multipart_upload(
                Bucket=self.settings.volume_id, Key=key.as_posix()
            ),
        )
        upload_id = created.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id:
            raise RunpodScenePreparationError("RunPod S3 did not return a multipart upload ID")

        total_parts = math.ceil(size_bytes / MULTIPART_PART_SIZE_BYTES)
        logger.info("Uploading %s in %s multipart parts", key, total_parts)
        try:
            parts = self._upload_parts(source, key, upload_id, size_bytes, total_parts)
            logger.info("Completing multipart upload for %s", key)
            self._complete_multipart_upload(key, upload_id, parts, size_bytes)
            self._verify_object_size(key, size_bytes)
        except BaseException:
            self._abort_multipart_upload(key, upload_id)
            raise

    def _upload_parts(
        self,
        source: Path,
        key: PurePosixPath,
        upload_id: str,
        size_bytes: int,
        total_parts: int,
    ) -> list[MultipartPart]:
        completed_parts = 0
        progress_lock = Lock()
        parts: list[MultipartPart] = []
        with ThreadPoolExecutor(max_workers=MULTIPART_WORKERS) as executor:
            futures = [
                executor.submit(
                    self._upload_part,
                    source,
                    key,
                    upload_id,
                    part_number,
                    (part_number - 1) * MULTIPART_PART_SIZE_BYTES,
                    min(
                        MULTIPART_PART_SIZE_BYTES,
                        size_bytes - (part_number - 1) * MULTIPART_PART_SIZE_BYTES,
                    ),
                )
                for part_number in range(1, total_parts + 1)
            ]
            for future in as_completed(futures):
                parts.append(future.result())
                with progress_lock:
                    completed_parts += 1
                    logger.info("Uploaded %s/%s parts for %s", completed_parts, total_parts, key)
        return sorted(parts, key=lambda part: part["PartNumber"])

    def _upload_part(
        self,
        source: Path,
        key: PurePosixPath,
        upload_id: str,
        part_number: int,
        offset: int,
        length: int,
    ) -> MultipartPart:
        with source.open("rb") as content:
            content.seek(offset)
            body = content.read(length)
        if len(body) != length:
            raise RunpodScenePreparationError(f"Unable to read part {part_number} from {source}")
        response = self._request(
            f"upload part {part_number} for {key}",
            lambda: self._client.upload_part(
                Bucket=self.settings.volume_id,
                Key=key.as_posix(),
                PartNumber=part_number,
                UploadId=upload_id,
                Body=body,
            ),
        )
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise RunpodScenePreparationError(
                f"RunPod S3 did not return an ETag for part {part_number}"
            )
        return MultipartPart(PartNumber=part_number, ETag=etag)

    def _complete_multipart_upload(
        self,
        key: PurePosixPath,
        upload_id: str,
        parts: list[MultipartPart],
        expected_size: int,
    ) -> None:
        timeout = max(S3_INITIAL_TIMEOUT_SECONDS, math.ceil(expected_size / GIBIBYTE) * 5)
        last_error: Exception | None = None
        for attempt in range(1, S3_MAX_RETRIES + 1):
            config = self._config.merge(
                Config(
                    connect_timeout=timeout,
                    read_timeout=timeout,
                    # The outer loop handles uncertain completion requests. Avoid multiple
                    # unreported Botocore retries, which can leave the terminal idle for minutes.
                    retries={"total_max_attempts": 1, "mode": "standard"},
                )
            )
            client = self._new_client(config)
            try:
                logger.info(
                    "Completing multipart upload for %s (attempt %s/%s; timeout %ss)",
                    key,
                    attempt,
                    S3_MAX_RETRIES,
                    timeout,
                )
                client.complete_multipart_upload(
                    Bucket=self.settings.volume_id,
                    Key=key.as_posix(),
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
                self._client = client
                self._config = config
                return
            except (BotoCoreError, ClientError) as exc:
                last_error = exc
                if _is_no_such_upload_error(exc):
                    logger.info("Multipart session ended; checking object state for %s", key)
                else:
                    logger.warning(
                        "Complete multipart upload for %s failed (attempt %s/%s): %s",
                        key,
                        attempt,
                        S3_MAX_RETRIES,
                        exc,
                    )

            if self._wait_for_completed_object(client, key, expected_size, timeout):
                logger.info("RunPod completed multipart upload for %s", key)
                self._client = client
                self._config = config
                return
            if attempt == S3_MAX_RETRIES:
                break
            timeout *= 2
            logger.info(
                "RunPod has not finished merging %s; retrying completion with a %ss timeout",
                key,
                timeout,
            )

        if last_error is not None:
            raise _s3_error(f"complete multipart upload for {key}", last_error) from last_error
        raise RunpodScenePreparationError(f"Unable to complete multipart upload for {key}")

    def _wait_for_completed_object(
        self, client: S3Client, key: PurePosixPath, expected_size: int, timeout: int
    ) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self._object_has_size(client, key, expected_size):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            wait_seconds = min(S3_COMPLETE_POLL_SECONDS, math.ceil(remaining))
            logger.info(
                "RunPod is still merging %s; checking again in %ss",
                key,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    def _object_has_size(self, client: S3Client, key: PurePosixPath, expected_size: int) -> bool:
        try:
            response = self._request_with_retry(
                f"check completed multipart upload for {key}",
                lambda: client.head_object(Bucket=self.settings.volume_id, Key=key.as_posix()),
            )
        except (BotoCoreError, ClientError):
            return False
        return response.get("ContentLength") == expected_size

    def _abort_multipart_upload(self, key: PurePosixPath, upload_id: str) -> None:
        try:
            self._request_with_retry(
                f"abort multipart upload for {key}",
                lambda: self._client.abort_multipart_upload(
                    Bucket=self.settings.volume_id,
                    Key=key.as_posix(),
                    UploadId=upload_id,
                ),
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning("Could not abort multipart upload for %s: %s", key, exc)

    def _verify_object_size(self, key: PurePosixPath, expected_size: int) -> None:
        response = self._request(
            f"verify upload for {key}",
            lambda: self._client.head_object(Bucket=self.settings.volume_id, Key=key.as_posix()),
        )
        if response.get("ContentLength") != expected_size:
            raise RunpodScenePreparationError(f"RunPod S3 size verification failed for {key}")

    def _new_client(self, config: Config) -> S3Client:
        return cast(
            S3Client,
            self._session.client("s3", config=config, endpoint_url=self.settings.endpoint_url),
        )

    def _request(self, description: str, operation: Callable[[], T]) -> T:
        try:
            return self._request_with_retry(description, operation)
        except (BotoCoreError, ClientError) as exc:
            raise _s3_error(description, exc) from exc

    def _request_with_retry(self, description: str, operation: Callable[[], T]) -> T:
        for attempt in range(1, S3_MAX_RETRIES + 1):
            retry_error: Exception | None = None
            try:
                return operation()
            except ClientError as exc:
                if not _is_retryable_s3_error(exc) or attempt == S3_MAX_RETRIES:
                    raise
                retry_error = exc
            except (ConnectTimeoutError, ReadTimeoutError) as exc:
                if attempt == S3_MAX_RETRIES:
                    raise
                retry_error = exc
            if retry_error is None:
                raise AssertionError("retry loop continued without a retryable error")
            logger.warning(
                "%s failed on attempt %s/%s: %s",
                description,
                attempt,
                S3_MAX_RETRIES,
                retry_error,
            )
            backoff_seconds = 2**attempt
            logger.info(
                "%s: retrying attempt %s/%s in %s seconds",
                description,
                attempt + 1,
                S3_MAX_RETRIES,
                backoff_seconds,
            )
            time.sleep(backoff_seconds)
        raise AssertionError("retry loop returned without a result")


def _is_retryable_s3_error(exc: ClientError) -> bool:
    metadata = exc.response.get("ResponseMetadata", {})
    status = metadata.get("HTTPStatusCode")
    return isinstance(status, int) and status in {500, 502, 503, 504, 524}


def _object_key(value: object) -> str:
    if not isinstance(value, dict):
        raise RunpodScenePreparationError("RunPod S3 returned an invalid object entry")
    key = value.get("Key")
    if not isinstance(key, str) or not key:
        raise RunpodScenePreparationError("RunPod S3 returned an object entry without a key")
    return key


def _object_size(value: object) -> int:
    if not isinstance(value, dict):
        raise RunpodScenePreparationError("RunPod S3 returned an invalid object entry")
    size = value.get("Size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise RunpodScenePreparationError("RunPod S3 returned an object entry without a size")
    return size


def _is_no_such_upload_error(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    error = exc.response.get("Error", {})
    return error.get("Code") == "NoSuchUpload"


def _is_not_found_error(exc: ClientError) -> bool:
    metadata = exc.response.get("ResponseMetadata", {})
    status = metadata.get("HTTPStatusCode")
    code = exc.response.get("Error", {}).get("Code")
    return (isinstance(status, int) and status == 404) or (
        isinstance(code, str) and code in {"404", "NoSuchKey", "NotFound"}
    )


def _s3_error(description: str, exc: Exception) -> RunpodScenePreparationError:
    return RunpodScenePreparationError(f"RunPod S3 failed to {description}: {exc}")


@dataclass(frozen=True, slots=True)
class PreparedScene:
    id: str
    name: str
    entrypoint: str


def prepare_scene(
    local_path: Path,
    settings: RunpodS3Settings,
    uploader: ObjectUploader,
    *,
    scene_id: str | None = None,
    scene_name: str | None = None,
) -> PreparedScene:
    """Upload a local BlendRender scene and publish its manifest last."""

    source_path = local_path.expanduser().resolve()
    if not source_path.is_file():
        raise RunpodScenePreparationError(f"Scene file not found: {local_path}")
    if source_path.stat().st_size <= 0:
        raise RunpodScenePreparationError("Scene files must not be empty")
    if source_path.stat().st_size > settings.max_upload_bytes:
        raise RunpodScenePreparationError("Scene exceeds the configured MAX_UPLOAD_GB limit")

    suffix = source_path.suffix.lower()
    if suffix not in {".blend", ".zip"}:
        raise RunpodScenePreparationError("Only .blend files and project ZIP archives are accepted")

    identifier = _scene_id(scene_id)
    name = _scene_name(scene_name, source_path.name)
    scene_root = settings.workspace_prefix / "scenes" / identifier
    scene_manifest_key = scene_root / "manifest.json"

    if scene_id is None:
        logger.info(
            "Assigned scene ID %s; reuse it with --scene-id to resume if interrupted",
            identifier,
        )
    else:
        logger.info("Preparing scene %s", identifier)
    uploader.ensure_volume()
    if uploader.object_exists(scene_manifest_key):
        raise RunpodScenePreparationError(
            f"Scene {identifier} is already complete on the network volume; "
            "choose a different --scene-id"
        )
    if not uploader.object_exists(settings.workspace_prefix / "workspace.json"):
        workspace = WorkspaceManifest(created_at=utc_now())
        uploader.upload_json(
            workspace.model_dump(mode="json"), settings.workspace_prefix / "workspace.json"
        )

    with _prepared_source(source_path, settings.max_upload_bytes) as prepared:
        source_files = {
            scene_root / "source" / relative_path: local_file
            for local_file, relative_path in prepared.files
        }
        existing_objects = uploader.list_object_sizes(scene_root)
        unexpected_objects = sorted(set(existing_objects).difference(source_files))
        if unexpected_objects:
            unexpected = unexpected_objects[0]
            if unexpected == scene_manifest_key:
                raise RunpodScenePreparationError(
                    f"Scene {identifier} is already complete on the network volume; "
                    "choose a different --scene-id"
                )
            raise RunpodScenePreparationError(
                f"Scene {identifier} contains unexpected existing object {unexpected}; "
                "choose a different --scene-id"
            )

        file_states: list[tuple[PurePosixPath, Path, int, int | None]] = []
        for key, local_file in source_files.items():
            expected_size = local_file.stat().st_size
            existing_size = existing_objects.get(key)
            if existing_size is not None and existing_size != expected_size:
                raise RunpodScenePreparationError(
                    f"Scene {identifier} contains {key} with size {existing_size}, but the "
                    f"current input has size {expected_size}; choose a different --scene-id"
                )
            file_states.append((key, local_file, expected_size, existing_size))

        for key, local_file, expected_size, existing_size in file_states:
            if existing_size is None:
                uploader.upload_file(local_file, key)
                continue
            logger.info("Skipping already uploaded %s (%s bytes)", key, expected_size)
        manifest = SceneManifest(
            id=identifier,
            filename=Path(prepared.entrypoint).name,
            name=name,
            source_kind=prepared.source_kind,
            entrypoint=prepared.entrypoint,
            created_at=utc_now(),
            size_bytes=source_path.stat().st_size,
        )
        # BlendRender lists a scene only after this immutable manifest is present.
        uploader.upload_json(manifest.model_dump(mode="json"), scene_manifest_key)

    return PreparedScene(id=identifier, name=name, entrypoint=manifest.entrypoint)


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    source_kind: Literal["blend", "zip"]
    entrypoint: str
    files: tuple[tuple[Path, PurePosixPath], ...]


@contextmanager
def _prepared_source(source_path: Path, max_upload_bytes: int) -> Iterator[_PreparedSource]:
    if source_path.suffix.lower() == ".blend":
        yield _PreparedSource(
            source_kind="blend",
            entrypoint="input.blend",
            files=((source_path, PurePosixPath("input.blend")),),
        )
        return

    try:
        with tempfile.TemporaryDirectory(prefix="blendrender-scene-") as directory:
            extracted_root = Path(directory) / "source"
            archive = inspect_project_archive(source_path, extracted_root, max_upload_bytes)
            available = shutil.disk_usage(directory).free
            if available < archive.total_size:
                raise RunpodScenePreparationError(
                    "Insufficient local temporary disk space to extract the project ZIP"
                )
            extract_project_archive(source_path, extracted_root, archive, max_upload_bytes)
            files = tuple(
                (path, PurePosixPath(path.relative_to(extracted_root).as_posix()))
                for path in sorted(extracted_root.rglob("*"))
                if path.is_file()
            )
            yield _PreparedSource(
                source_kind="zip",
                entrypoint=archive.scene_relative_path.as_posix(),
                files=files,
            )
    except ProjectArchiveError as exc:
        raise RunpodScenePreparationError(str(exc)) from exc


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RunpodScenePreparationError(f"{name} is required")
    return value


def _validate_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RunpodScenePreparationError("RUNPOD_S3_ENDPOINT must be an HTTPS endpoint URL")


def _workspace_prefix_from_env() -> PurePosixPath:
    configured = os.getenv("WORKSPACE_ROOT", "/workspace/blendrender").strip()
    workspace_root = PurePosixPath(configured)
    try:
        prefix = workspace_root.relative_to("/workspace")
    except ValueError as exc:
        raise RunpodScenePreparationError(
            "WORKSPACE_ROOT must be under /workspace, or set it to the Pod's workspace path"
        ) from exc
    if not prefix.parts or any(part in {"", ".", ".."} for part in prefix.parts):
        raise RunpodScenePreparationError("WORKSPACE_ROOT must name a subdirectory of /workspace")
    return prefix


def _max_upload_bytes_from_env() -> int:
    try:
        gibibytes = float(os.getenv("MAX_UPLOAD_GB", "20"))
    except ValueError as exc:
        raise RunpodScenePreparationError("MAX_UPLOAD_GB must be a positive number") from exc
    if not math.isfinite(gibibytes) or gibibytes <= 0:
        raise RunpodScenePreparationError("MAX_UPLOAD_GB must be a positive number")
    bytes_limit = int(gibibytes * 1024**3)
    if bytes_limit <= 0:
        raise RunpodScenePreparationError("MAX_UPLOAD_GB must be a positive number")
    return bytes_limit


def _scene_id(value: str | None) -> str:
    if value is None:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise RunpodScenePreparationError("--scene-id must be a UUID") from exc


def _scene_name(value: str | None, fallback: str) -> str:
    candidate = value if value is not None else fallback
    basename = unicodedata.normalize("NFKC", candidate).replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(character if character.isprintable() else " " for character in basename)
    sanitized = " ".join(printable.split()).strip(" .")[:200].rstrip()
    if sanitized:
        return sanitized
    raise RunpodScenePreparationError("--name must contain a printable filename")
