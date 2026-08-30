# Architecture

BlendRender is a scene-centric renderer for multiple peer RunPod Pods sharing one network volume.
Every Pod serves the dashboard and API, owns one local Blender worker, and reads the same scene,
job, and result catalog from `/workspace/blendrender`.

## Domain model

- A **scene** is an immutable `.blend` upload or safely extracted project ZIP.
- A **job** references one scene, records render settings, and is permanently owned by the Pod that
  created it. Only that Pod can render, cancel, retry, or delete the job.
- A **result** is an immutable frame render. It belongs to a scene and records its job, pod,
  backend, actual hardware, effective samples, and frame render duration.

Jobs are not distributed or reassigned. Parallel work comes from creating jobs through different Pod
dashboards. Each Pod still runs at most one Blender subprocess at once.

## Shared workspace

```text
/workspace/blendrender/
├── workspace.json
├── scenes/{scene-id}/source/ and results/{frame}/{result-id}/
├── jobs/{job-id}/manifest.json, status.json, render.log, pending/
├── nodes/{pod-id}/status.json and telemetry.json
├── staging/
├── locks/
├── tombstones/
└── trash/
```

Scene and job manifests are immutable. A job's owner is its only status/log writer. A rendered
frame is staged, verified as PNG, previewed as WebP, given metadata, and atomically renamed into
its scene result directory. Therefore two jobs may render the same scene/frame without overwrite;
both result variants are visible everywhere.

The store has no shared SQLite database. Network-volume writes are partitioned by owner and JSON
snapshots are atomically replaced. Scene/job deletion uses a short scene lock and a tombstone to
prevent racing job creation. Deleted scene data is moved under `trash/` for recovery cleanup.

## Lifecycle and recovery

`queued → running → completed`, with `failed`, `canceled`, and `interrupted` terminal states.
Retries render only frames that do not already have a published result for that job. On process
restart, a Pod marks only its own running jobs interrupted; its queued jobs remain runnable.

Pods publish heartbeats while collecting local telemetry. Other dashboards can identify a stale
job owner, but such jobs remain read-only history and are never taken over.
