# Architecture

Each Pod serves the dashboard and API, runs one Blender worker, and reads a shared catalog from
`WORKSPACE_ROOT`. Production uses one Uvicorn process per Pod and renders one job at a time.

## Core concepts

- **Scene:** an uploaded `.blend` or extracted project ZIP with an immutable manifest and source.
  The [S3 guide](s3-guide.md#replace-scene-source-files) documents an offline source-replacement
  exception.
- **Job:** a scene, render settings, and a permanent owner Pod. Only the owner can render, cancel,
  retry, or delete the job directly.
- **Result:** an immutable frame render with its job, Pod, backend, hardware, samples, and duration.

All Pods see the same catalog. Jobs are never distributed or reassigned: create jobs through
different Pod dashboards to render in parallel.

## Shared workspace

```text
/workspace/blendrender/
├── workspace.json
├── scenes/{scene-id}/
│   ├── manifest.json
│   ├── source/
│   └── results/{frame}/{result-id}/
├── jobs/{job-id}/
│   ├── manifest.json
│   ├── status.json
│   ├── render.log
│   └── pending/
├── nodes/{pod-id}/
│   ├── status.json
│   └── telemetry.json
├── staging/{upload-id}/
├── locks/
├── tombstones/
└── trash/
```

State uses versioned JSON snapshots published atomically, without a shared database. Job manifests
are immutable; only the owner writes status and logs. Rendered frames are staged, verified as PNG,
given previews and metadata, then atomically published under unique result IDs.

Upload chunks are written under `staging/` with a checkpointed offset. A shared lock serializes
chunks and finalization. After validation and extraction, the scene is published atomically.
Inactive staging uploads expire after 24 hours.

Scene and job deletion use scene locks; scene deletion also leaves a tombstone to block new jobs.
Deleting a scene moves its data and jobs to `trash/`. Deleting an individual job removes its job
directory. Direct S3 deletions bypass trash.

## Recovery

Jobs normally move from `queued` to `running` to `completed`. Other terminal states are `failed`,
`canceled`, and `interrupted`. Retries preserve verified results and render only missing frames.

On restart, a Pod marks its own running jobs interrupted and keeps its queued jobs runnable. Pods
publish heartbeats and local telemetry; a stale owner remains visible, but other Pods never take
over its jobs. If that owner does not return, its jobs remain read-only history.
