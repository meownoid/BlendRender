# HTTP API

All `/api` routes require the signed session cookie except login, logout, and session inspection.
Mutating browser requests must be same-origin.

## Scenes

`POST /api/scenes` accepts multipart `file` only. The file must be a non-empty `.blend` or project
ZIP containing exactly one `.blend` and safe relative assets. It returns a scene object. Uploading
a scene never queues a render.

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
  "samples": 128
}
```

For `mode: "still"`, provide `frame`. Optional `samples`, `resolution_x` plus `resolution_y`, and
`resolution_percentage` retain the existing limits; omitted values use the scene setting. The
backend must be available on the receiving Pod. The response records `owner_pod_id` and
`owner_online`.

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
