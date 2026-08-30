# Deployment and operations

## Shared RunPod deployment

Deploy the same image to every peer Pod and attach the same Secure Cloud network volume during Pod
creation. RunPod mounts that volume at `/workspace`; BlendRender stores its v2 workspace in
`/workspace/blendrender` by default. All peer Pods must run the same BlendRender version and have a
common `APP_PASSWORD` for a consistent operator experience.

Each Pod is a complete dashboard/API instance and renders only jobs created through its own URL.
Use multiple Pod dashboards to run multiple jobs for the same scene in parallel. A network-volume
Pod cannot be stopped, only terminated; terminated-owner jobs remain shared read-only history.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PASSWORD` | required | Operator password and cookie-signing source |
| `WORKSPACE_ROOT` | `/workspace/blendrender` | Shared scenes, jobs, results, node heartbeats, and telemetry |
| `BLENDRENDER_POD_ID` | `RUNPOD_POD_ID`, then hostname | Development override for Pod ownership |
| `BLENDER_BIN` | `/opt/blender/blender` | Blender executable |
| `RENDERER_SCRIPT` | bundled renderer | Blender-side runner |
| `MAX_UPLOAD_GB` | `5` | Upload and extracted ZIP limit |
| `COOKIE_SECURE` | `true` | Restrict cookies to HTTPS |
| `AVAILABLE_BACKENDS` | probe | Development/test backend override |

The container starts as root only long enough to create and own its workspace subdirectory, then
drops to UID/GID `10001`. Preserve `/workspace/blendrender`; container disk is suitable only for
temporary files and archive responses.

## Health and verification

`/healthz` checks the web process. `/readyz` requires Blender and at least one usable backend.
`/api/system` and `/api/system/telemetry` describe the Pod serving that URL, not a fleet aggregate.

Build with `just docker-build`. Before release, attach one network volume to two real Pods, upload a
scene once, create same-frame jobs through both dashboards, and confirm both distinct result
variants appear from each Pod URL.
