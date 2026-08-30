#!/bin/sh
set -eu

mkdir -p "${WORKSPACE_ROOT:?WORKSPACE_ROOT is required}"
chown 10001:10001 "$WORKSPACE_ROOT"
exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
