# HTTP API

All `/api` routes require the signed session cookie except login, logout, and session inspection.
Mutating browser requests must be same-origin.

## Scenes

Create a scene through an authenticated resumable upload session. The browser sends at most 8 MiB
per request by default, avoiding long-lived RunPod proxy connections and writing directly to the
shared workspace. Operators may set `UPLOAD_CHUNK_MB` to another positive whole-MiB value.

`POST /api/uploads` accepts JSON with `filename`, `size_bytes`, and optional `name`; it returns an
upload session containing its UUID, byte offset, chunk size, expiry, and status. The filename must
end in `.blend` or `.zip`, and its declared size must not exceed `MAX_UPLOAD_GB`.

`PATCH /api/uploads/{id}` accepts raw `application/octet-stream` bytes and an `Upload-Offset`
header. Send exactly the next contiguous chunk, no larger than the returned `chunk_size_bytes`.
The response confirms the committed `uploaded_bytes`. On a `409`, use the returned session or
`Upload-Offset` response header to resume from the server's committed offset.

`POST /api/uploads/{id}/complete` begins validation and extraction after all bytes arrive and
returns `202` immediately. Poll `GET /api/uploads/{id}` until it reports `completed` with a `scene`
object, or `failed` with an error. `DELETE /api/uploads/{id}` discards an unfinished transfer.
Inactive or failed staging uploads expire after 24 hours; a finalizing upload is recovered after an
application restart.

A complete upload must be a non-empty `.blend` or project ZIP containing exactly one `.blend` and
safe relative assets. Uploading a scene never queues a render. ZIPs may contain up to 100,000
entries and are limited by both compressed upload bytes and extracted regular-file bytes.

`GET /api/scenes` lists shared scenes. `GET /api/scenes/{id}` returns one. `DELETE /api/scenes/{id}`
removes its source, results, and terminal jobs; it returns `409` while any associated job is queued
or running.

## Jobs

`POST /api/jobs` accepts JSON:

```json
{
  "scene_id": "uuid",
  "mode": "range",
  "start": 1,
  "end": 120,
  "backend": "OPTIX",
  "samples": 128,
  "tile_size": 256
}
```

For `mode: "still"`, provide `frame`. Optional `samples`, `tile_size` (8–8192),
`resolution_x` plus `resolution_y`, and `resolution_percentage` retain the existing limits;
omitted values use the scene setting. The backend must be available on the receiving Pod. The
response records `owner_pod_id` and `owner_online`.

`GET /api/jobs` supports optional `scene_id` and `status`. Job detail is `GET /api/jobs/{id}`.
Cancel, retry, and delete use the existing `/cancel`, `/retry`, and `DELETE` routes, but only the
owning Pod may mutate a job; other Pods receive `409` and continue to show it read-only.

## Results and archives

`GET /api/scenes/{id}/frames?cursor=&limit=` returns descending frame groups. Each group includes
every completed result variant for that frame. A result includes its backend, device names, samples,
render duration, job ID, and pod ID.

`GET /api/scenes/{id}/results/{result-id}` reads metadata. Append `/image?preview=true` for WebP or
omit the query for the PNG download. `POST /api/scenes/{id}/archive` accepts
`{"result_ids":["..."]}` or `{"result_ids":null}` for all scene results; archives include PNGs and
their JSON metadata. `POST /api/jobs/{id}/archive` packages that job's published results.
