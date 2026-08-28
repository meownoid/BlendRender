#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.cookiejar
import json
import struct
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = "application/json",
        expected: int = 200,
    ) -> tuple[bytes, dict[str, str]]:
        headers = {"Content-Type": content_type} if content_type else {}
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                payload = response.read()
                status = response.status
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            response_headers = dict(exc.headers.items())
        if status != expected:
            raise RuntimeError(
                f"{method} {path} returned {status}, expected {expected}: "
                f"{payload.decode(errors='replace')}"
            )
        return payload, response_headers

    def json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: int = 200,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        raw, _ = self.request(method, path, body=body, expected=expected)
        return json.loads(raw) if raw else {}


def multipart_job(blend_path: Path) -> tuple[bytes, str]:
    boundary = f"blendqueue-e2e-{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )

    field("mode", "still")
    field("backend", "CPU")
    field("frame", "1")
    field("samples", "1")
    field("resolution_x", "320")
    field("resolution_y", "180")
    field("resolution_percentage", "5")
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{blend_path.name}"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            blend_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise BlendQueue through its public API")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    if not args.blend.is_file():
        raise SystemExit(f"Blend fixture not found: {args.blend}")
    client = Client(args.base_url)
    assert client.json("POST", "/api/auth/login", {"password": args.password}) == {
        "authenticated": True
    }
    system = client.json("GET", "/api/system")
    assert "CPU" in system["available_backends"]

    upload, content_type = multipart_job(args.blend)
    raw, _ = client.request(
        "POST", "/api/jobs", body=upload, content_type=content_type, expected=201
    )
    job = json.loads(raw)
    assert job["backend"] == "CPU"
    assert job["samples"] == 1
    assert job["resolution_x"] == 320
    assert job["resolution_y"] == 180
    assert job["resolution_percentage"] == 5
    job_id = job["id"]
    print(f"queued {job_id} from {args.blend.name}", flush=True)

    deadline = time.monotonic() + args.timeout
    last_status = None
    while time.monotonic() < deadline:
        job = client.json("GET", f"/api/jobs/{job_id}")
        status = job["status"]
        if status != last_status:
            print(f"status={status} progress={job['progress']:.1f}%", flush=True)
            last_status = status
        if status == "completed":
            break
        if status in {"failed", "canceled", "interrupted"}:
            error = f"render ended as {status}: {job.get('error')}\n{job.get('log_tail')}"
            raise RuntimeError(error)
        time.sleep(1)
    else:
        raise RuntimeError(f"render did not complete within {args.timeout:.0f}s")

    png, _ = client.request("GET", f"/api/jobs/{job_id}/frames/1", content_type=None)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (16, 9)
    preview, _ = client.request(
        "GET", f"/api/jobs/{job_id}/frames/1?preview=true", content_type=None
    )
    assert preview[:4] == b"RIFF" and preview[8:12] == b"WEBP"
    archive, _ = client.request(
        "POST",
        f"/api/jobs/{job_id}/archive",
        body=json.dumps({"frames": [1]}).encode(),
    )
    with zipfile.ZipFile(BytesIO(archive)) as bundle:
        assert bundle.namelist() == ["frame_000001.png"]
        assert bundle.read("frame_000001.png").startswith(b"\x89PNG")

    client.request("DELETE", f"/api/jobs/{job_id}", expected=204)
    client.request("GET", f"/api/jobs/{job_id}", expected=404)
    print("BlendQueue backend E2E passed", flush=True)


if __name__ == "__main__":
    main()
