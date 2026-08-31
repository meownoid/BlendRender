#!/bin/sh
set -eu

mkdir -p "${WORKSPACE_ROOT:?WORKSPACE_ROOT is required}"

# /workspace can be a RunPod network volume.  Its contents may be populated by
# peer Pods or RunPod's S3-compatible API, neither of which guarantees that
# ownership changes are supported by the mounted filesystem.
if [ "$(id -u)" -eq 0 ]; then
    exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi

exec "$@"
