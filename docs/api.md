# HTTP API

All `/api` routes require a signed session cookie except the authentication routes below.
Browser mutations must be same-origin.

## Authentication and system status

| Method and path | Behavior |
| --- | --- |
| `POST /api/auth/login` | Accepts `{"password":"..."}` and sets the session cookie |
| `POST /api/auth/logout` | Clears the cookie |
| `GET /api/auth/session` | Returns `{"authenticated":true}` or `{"authenticated":false}` |
| `GET /api/system` | Current Pod's hardware, available backends, and storage |
| `GET /api/system/telemetry` | Current Pod's recent performance samples |

Unauthenticated requests to protected routes return `401`. Public `/healthz` and `/readyz` are in
[Deployment](deployment.md#health-checks).

## Uploads and scenes

Upload a non-empty `.blend` or a ZIP with exactly one `.blend` and safe relative assets.
`MAX_UPLOAD_GB` limits both the upload and extracted files (20 GiB by default); ZIPs may contain
at most 100,000 entries. See [scene preparation](rendering.md#prepare-a-scene).

1. `POST /api/uploads` with JSON fields `filename`, `size_bytes`, and optional `name`. Returns `201` with the
   session ID, `uploaded_bytes`, `chunk_size_bytes`, expiry, and status.
2. `PATCH /api/uploads/{id}` with raw `application/octet-stream` bytes and an `Upload-Offset` header.
   Send contiguous chunks no larger than `chunk_size_bytes` (32 MiB by default). The response confirms
   `uploaded_bytes`. On `409`, resume from the returned session or `Upload-Offset` response header.
3. `POST /api/uploads/{id}/complete` after all bytes arrive. Returns `202` while validation and
   extraction run. Poll `GET /api/uploads/{id}` for `completed` with a `scene`, or `failed` with an
   error.

`DELETE /api/uploads/{id}` discards an unfinished transfer unless finalization is in progress.
Inactive and failed uploads expire after 24 hours; finalization recovers after a restart.
Uploading a scene does not queue a render.

| Method and path | Behavior |
| --- | --- |
| `GET /api/scenes` | List shared scenes |
| `GET /api/scenes/{id}` | Read one scene |
| `DELETE /api/scenes/{id}` | Delete source, results, and terminal jobs; `409` if any job is queued or running |

## Jobs

Create a job with `POST /api/jobs` and a JSON body:

```json
{
  "scene_id": "SCENE_UUID",
  "mode": "range",
  "start": 1,
  "end": 120,
  "backend": "OPTIX",
  "samples": 128
}
```

Returns `201` with the job, including `owner_pod_id` and `owner_online`.

For `mode: "still"`, provide `frame` instead of `start` and `end`. Ranges are inclusive, must have
`start <= end`, and may contain at most 100,000 frames. `backend` is `OPTIX`, `CUDA`, or `CPU` and
must be available on the receiving Pod.

Omitted overrides use scene settings:

| Field | Allowed values |
| --- | --- |
| `samples` | 1–1,000,000 |
| `tile_size` | 8–8,192 |
| `resolution_x`, `resolution_y` | 4–65,536 each; provide both together |
| `resolution_percentage` | 1–100 |

| Method and path | Behavior |
| --- | --- |
| `GET /api/jobs` | List jobs; optional `scene_id` and `status` filters |
| `GET /api/jobs/{id}` | Read settings, progress, status, and log tail |
| `POST /api/jobs/{id}/cancel` | Cancel a queued or running job |
| `POST /api/jobs/{id}/retry` | Retry a failed, canceled, or interrupted job, retaining completed frames |
| `DELETE /api/jobs/{id}` | Delete a terminal job; preserve published results |

Mutations must reach the owning Pod. Another Pod, or an invalid state transition, returns `409`.
Status values are `queued`, `running`, `completed`, `failed`, `canceled`, and `interrupted`.

## Results and archives

| Method and path | Behavior |
| --- | --- |
| `GET /api/scenes/{id}/frames` | Descending frame groups, each with all result variants |
| `GET /api/scenes/{id}/results/{result-id}` | Result metadata |
| `GET /api/scenes/{id}/results/{result-id}/image` | PNG; add `?preview=true` for WebP |
| `POST /api/scenes/{id}/archive` | ZIP of selected results, or all scene results |
| `POST /api/jobs/{id}/archive` | ZIP of that job's results; no request body |

Frame pages accept `limit` (1–200, default 50) and an optional frame-number `cursor` to request
frames below that number. Metadata includes backend, hardware, samples, render duration, job ID,
and Pod ID.
Scene archives accept `{"result_ids":["RESULT_UUID"]}` or `{"result_ids":null}` for all results.
ZIPs include PNGs and JSON metadata.
