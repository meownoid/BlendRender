#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.cookiejar
import json
import struct
import time
import urllib.error
import urllib.request
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
        headers: dict[str, str] | None = None,
        expected: int = 200,
    ) -> tuple[bytes, dict[str, str]]:
        request_headers = {"Content-Type": content_type} if content_type else {}
        request_headers.update(headers or {})
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=request_headers, method=method
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


def project_zip(blend_path: Path) -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"project/scenes/{blend_path.name}", blend_path.read_bytes())
        bundle.writestr("project/resources/.keep", b"")
    return payload.getvalue()


def upload_scene(client: Client, filename: str, content: bytes, timeout: float) -> dict[str, Any]:
    upload = client.json(
        "POST",
        "/api/uploads",
        {"filename": filename, "size_bytes": len(content)},
        expected=201,
    )
    offset = 0
    while offset < len(content):
        chunk = content[offset : offset + upload["chunk_size_bytes"]]
        raw, _ = client.request(
            "PATCH",
            f"/api/uploads/{upload['id']}",
            body=chunk,
            content_type="application/octet-stream",
            headers={"Upload-Offset": str(offset)},
        )
        upload = json.loads(raw)
        offset = upload["uploaded_bytes"]
    upload = client.json("POST", f"/api/uploads/{upload['id']}/complete", expected=202)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if upload["status"] == "completed" and upload["scene"] is not None:
            return upload["scene"]
        if upload["status"] == "failed":
            raise RuntimeError(f"upload failed: {upload.get('error')}")
        time.sleep(0.2)
        upload = client.json("GET", f"/api/uploads/{upload['id']}")
    raise RuntimeError(f"upload did not complete within {timeout:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise BlendRender through its public API")
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

    scene = upload_scene(client, "project.zip", project_zip(args.blend), args.timeout)
    scene_id = scene["id"]
    job = client.json(
        "POST",
        "/api/jobs",
        {
            "scene_id": scene_id,
            "mode": "still",
            "backend": "CPU",
            "frame": 1,
            "samples": 1,
            "resolution_x": 320,
            "resolution_y": 180,
            "resolution_percentage": 5,
        },
        expected=201,
    )
    assert job["backend"] == "CPU"
    assert job["samples"] == 1
    assert job["resolution_x"] == 320
    assert job["resolution_y"] == 180
    assert job["resolution_percentage"] == 5
    assert job["scene_id"] == scene_id
    job_id = job["id"]
    print(f"queued {job_id} from scene {scene_id}", flush=True)

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

    frames = client.json("GET", f"/api/scenes/{scene_id}/frames")
    result = frames["items"][0]["results"][0]
    result_id = result["id"]
    png, _ = client.request(
        "GET", f"/api/scenes/{scene_id}/results/{result_id}/image", content_type=None
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (16, 9)
    preview, _ = client.request(
        "GET",
        f"/api/scenes/{scene_id}/results/{result_id}/image?preview=true",
        content_type=None,
    )
    assert preview[:4] == b"RIFF" and preview[8:12] == b"WEBP"
    archive, _ = client.request(
        "POST",
        f"/api/scenes/{scene_id}/archive",
        body=json.dumps({"result_ids": [result_id]}).encode(),
    )
    with zipfile.ZipFile(BytesIO(archive)) as bundle:
        names = bundle.namelist()
        assert len(names) == 2
        assert next(name for name in names if name.endswith(".png"))
        assert next(name for name in names if name.endswith(".json"))
        assert bundle.read(next(name for name in names if name.endswith(".png"))).startswith(
            b"\x89PNG"
        )

    client.request("DELETE", f"/api/jobs/{job_id}", expected=204)
    client.request("GET", f"/api/jobs/{job_id}", expected=404)
    print("BlendRender backend E2E passed", flush=True)


if __name__ == "__main__":
    main()
