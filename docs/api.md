# HTTP API

BlendRender exposes JSON and multipart endpoints below `/api`. Interactive OpenAPI and ReDoc pages
are disabled in production, so this document is the human-facing reference.

## Authentication

`POST /api/auth/login` accepts JSON:

```json
{"password": "your APP_PASSWORD"}
```

On success, the response is `{"authenticated": true}` and includes the signed
`blendrender_session` cookie. Send that cookie on later requests. The cookie is HTTP-only,
same-site strict, and secure by default. After ten failed attempts, further attempts within the
rolling minute return `429`.

`GET /api/auth/session` reports whether the current cookie is authenticated. `POST /api/auth/logout`
clears it. These three authentication routes do not require an existing authenticated cookie.

Browser-originating mutating requests with a foreign `Origin` are rejected. Scripts that omit the
`Origin` header can use the API normally.

## Example session

```bash
base_url='http://localhost:8000'

curl --fail --silent --show-error \
  --cookie-jar /tmp/blendrender-cookies \
  -H 'Content-Type: application/json' \
  -d '{"password":"blendrender-dev"}' \
  "$base_url/api/auth/login"

curl --fail --silent --show-error \
  --cookie /tmp/blendrender-cookies \
  "$base_url/api/system"
```

Use a private cookie-jar location in shared environments and remove it after use.

## System and probes

| Method and path | Authentication | Result |
| --- | --- | --- |
| `GET /healthz` | No | `200` when the web process can answer requests |
| `GET /readyz` | No | `200` when Blender and at least one render backend are available; otherwise `503` |
| `GET /api/system` | Yes | Latest server-collected Blender version, host CPU/RAM and GPU telemetry, available backends, and data-disk capacity |
| `GET /api/system/telemetry` | Yes | Chronological server-persisted CPU, GPU, host-memory, and VRAM samples from the last 15 minutes |

Readiness accepts CPU as a backend. The response includes `cpu_utilization` (0–100),
`memory_used_bytes`, and `memory_total_bytes` for the node environment. GPU telemetry comes from
`nvidia-smi`; backend availability is probed once at application startup.

The server collects telemetry every 5 seconds while work is queued or running and every 10 seconds
while idle. `GET /api/system/telemetry` returns samples with `captured_at`, `cpu_utilization`,
nullable `gpu_utilization`, `memory_used_bytes`, `memory_total_bytes`, nullable `vram_used_mb`, and
nullable `vram_total_mb`. The rolling 15-minute history is stored in SQLite and survives browser
refreshes and application restarts.

## Create a job

`POST /api/jobs` uses `multipart/form-data` and returns `201` with a job object.

| Field | Required | Rules |
| --- | --- | --- |
| `file` | Yes | Non-empty `.blend` or `.zip`; uploaded bytes may not exceed `MAX_UPLOAD_GB`. A ZIP must contain exactly one `.blend`, at most 10,000 regular-file/directory entries, and no encrypted, symlink, duplicate, absolute, or traversal paths. Its expanded regular-file bytes may not exceed `MAX_UPLOAD_GB`. |
| `mode` | Yes | `still` or `range` |
| `backend` | Yes | `OPTIX`, `CUDA`, or `CPU`; must be available on the node |
| `frame` | For `still` | Integer frame number |
| `start`, `end` | For `range` | Integer bounds; `start <= end`; no more than 100,000 frames |
| `samples` | No | `1` through `1,000,000` |
| `resolution_x`, `resolution_y` | No | Must be supplied together; each is `4` through `65,536` |
| `resolution_percentage` | No | `1` through `100` |

The request is rejected with `507` when less than 1 GiB is free before upload begins. Optional
render fields preserve the corresponding active-scene value when omitted.

Project ZIPs preserve their internal directory layout. Blender resources must use relative paths
that resolve inside the archive; BlendRender does not rewrite or search for asset paths. After the
ZIP is uploaded, the service also requires enough free disk for its declared extracted size plus
1 GiB of headroom and returns `507` if that check fails.

Still-render example:

```bash
curl --fail --silent --show-error \
  --cookie /tmp/blendrender-cookies \
  -F file=@scene.blend \
  -F mode=still \
  -F frame=1 \
  -F backend=CPU \
  -F samples=64 \
  -F resolution_x=1920 \
  -F resolution_y=1080 \
  -F resolution_percentage=50 \
  "$base_url/api/jobs"
```

Frame-range example:

```bash
curl --fail --silent --show-error \
  --cookie /tmp/blendrender-cookies \
  -F file=@animation.blend \
  -F mode=range \
  -F start=1 \
  -F end=120 \
  -F backend=OPTIX \
  "$base_url/api/jobs"
```

Project ZIP example:

```bash
curl --fail --silent --show-error \
  --cookie /tmp/blendrender-cookies \
  -F file=@project.zip \
  -F mode=still \
  -F frame=1 \
  -F backend=CPU \
  "$base_url/api/jobs"
```

## Jobs

| Method and path | Behavior |
| --- | --- |
| `GET /api/jobs` | Lists newest first; optional `?status=queued|running|completed|failed|canceled|interrupted` |
| `GET /api/jobs/{id}` | Gets one job |
| `POST /api/jobs/{id}/cancel` | Cancels a queued or running job; other states return `409` |
| `POST /api/jobs/{id}/retry` | Requeues a failed, canceled, or interrupted job; other states return `409` |
| `DELETE /api/jobs/{id}` | Deletes a terminal job and its files; active states return `409` |

The job response includes identifiers and requested settings, `status`, `progress`, current and
completed frames, current-frame sample telemetry (`sample_current` and `sample_total` while
available), timestamps, elapsed/estimated seconds, an error message, a bounded `log_tail`, and
`cancel_requested`. Timestamps are UTC ISO 8601 strings.

## Frames and archives

`GET /api/jobs/{id}/frames/{frame}` downloads the PNG output as
`frame_000001.png`. Add `?preview=true` to retrieve the generated WebP preview inline. A frame
outside the job range, or an output not yet available, returns `404`.

`POST /api/jobs/{id}/archive` accepts JSON. Pass explicit completed frames:

```json
{"frames": [1, 2, 3]}
```

Pass `{"frames": null}` to include every completed frame. The response is a temporary uncompressed
ZIP named from the source project. Empty selections and unavailable frames return `422`.

```bash
curl --fail --silent --show-error \
  --cookie /tmp/blendrender-cookies \
  -H 'Content-Type: application/json' \
  -d '{"frames":null}' \
  --output frames.zip \
  "$base_url/api/jobs/$job_id/archive"
```
