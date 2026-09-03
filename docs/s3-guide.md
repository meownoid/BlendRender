# RunPod S3 scripts guide

Use these scripts to prepare scenes before starting a Pod, download results, or clean up a network
volume. Run commands from the repository root.

**Before uploading or deleting data, make sure no Pod or other script is writing to the network
volume.** These scripts bypass the application's workspace locks. Source replacement also requires
that no Pod is rendering the scene.

## Set up credentials

Install dependencies with `uv sync`, then create a RunPod **S3 API key** and export its credentials:

```bash
export AWS_ACCESS_KEY_ID='YOUR_S3_ACCESS_KEY'
export AWS_SECRET_ACCESS_KEY='YOUR_S3_SECRET_KEY'
export RUNPOD_NETWORK_VOLUME_ID='NETWORK_VOLUME_ID'
export RUNPOD_S3_REGION='YOUR_DATACENTER_ID'
export WORKSPACE_ROOT='/workspace/blendrender'
```

Use the volume ID, not its display name. The region is the volume's datacenter, such as `EUR-IS-1`.
The endpoint is derived from the region; set `RUNPOD_S3_ENDPOINT` only to override it.
`WORKSPACE_ROOT` must match the Pod's path under `/workspace`; the default maps to the `blendrender/`
S3 prefix. Keep credentials out of version control.

## Upload a scene

```bash
uv run python scripts/prepare_runpod_scene.py /path/to/project.zip --name 'Final exterior'
```

Accepts a `.blend` or a ZIP following the [scene requirements](rendering.md#prepare-a-scene).
The scene becomes visible only after all source files upload successfully. ZIPs are extracted
locally first, so allow enough temporary disk space. `MAX_UPLOAD_GB` defaults to 20 GiB and limits
both the input and extracted files.

The script prints the scene ID before transfer. To resume an interrupted upload, reuse the same
input and ID:

```bash
uv run python scripts/prepare_runpod_scene.py /path/to/project.zip \
  --name 'Final exterior' --scene-id 'SCENE_UUID'
```

Resume skips files with matching paths and byte sizes; it does not compare file contents. Changed
sizes, unexpected objects, or an already completed scene cause the script to refuse the upload.

Use `--upload-workers 1` through `--upload-workers 16` to adjust concurrency; the default is eight.
Large files use multipart transfers. Retries and progress are logged, and uploaded sizes are checked.

## Replace scene source files

To update a completed scene while keeping its textures, caches, jobs, and results:

```bash
uv run python scripts/prepare_runpod_scene.py /path/to/updated.blend \
  --scene-id 'SCENE_UUID' --overwrite
```

`--overwrite` replaces only supplied source files. A standalone `.blend` replaces the recorded
entrypoint, including for a scene originally uploaded as a ZIP. A ZIP update requires an original
ZIP scene and the same relative `.blend` path.

Omitted files and the scene manifest remain unchanged; `--name` cannot be used with `--overwrite`.
This is an offline exception to scene immutability. Existing results still describe the old source;
upload a new scene instead if you need a separate history.

## List and download results

```bash
uv run python scripts/manage_runpod_scenes.py list
uv run python scripts/manage_runpod_scenes.py list --scene-id 'SCENE_UUID' --json

uv run python scripts/manage_runpod_scenes.py download \
  --scene-id 'SCENE_UUID' --download-dir ./blendrender-results
```

`list` shows completed scene uploads, their jobs and statuses, and published results. Omit
`--scene-id` from `download` to download results for all scenes.

Downloads include `frame.png`, `preview.webp`, and `metadata.json`, preserving the
`scenes/{scene-id}/results/...` layout. The destination may already contain files; matching local
paths are skipped and never overwritten. `--transfer-workers` accepts 1–16, with a default of eight.

## Delete selected data

**S3 deletions are permanent and bypass workspace trash.** Each command requires an ID or `--all`,
plus the exported network-volume ID as confirmation.

| Command | Removes | Preserves |
| --- | --- | --- |
| `delete-results` | Selected result packages | Scenes and jobs |
| `delete-jobs` | Selected jobs | Scenes and published results |
| `delete-scenes` | Selected scenes, sources, results, and terminal jobs | Other scenes |

Job and scene deletion refuse queued or running jobs. Inspect the inventory before deleting:

```bash
uv run python scripts/manage_runpod_scenes.py delete-results \
  --result-id 'RESULT_UUID' --confirm "$RUNPOD_NETWORK_VOLUME_ID"

uv run python scripts/manage_runpod_scenes.py delete-jobs \
  --job-id 'JOB_UUID' --confirm "$RUNPOD_NETWORK_VOLUME_ID"

uv run python scripts/manage_runpod_scenes.py delete-scenes \
  --scene-id 'SCENE_UUID' --confirm "$RUNPOD_NETWORK_VOLUME_ID"
```

Replace the ID option with `--all` to delete every item of that type.

## Clear the entire volume

This removes **every object on the volume**, including data outside BlendRender, and aborts
incomplete multipart uploads. The volume itself remains. Ensure all writers are inactive first.

Preview the scope without changing data:

```bash
uv run python scripts/clear_runpod_volume.py --dry-run
```

Then, only if the entire volume can be erased:

```bash
uv run python scripts/clear_runpod_volume.py --confirm "$RUNPOD_NETWORK_VOLUME_ID"
```

Deletion is irreversible and can take time for volumes with many files.
