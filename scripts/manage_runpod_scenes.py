#!/usr/bin/env python3
"""Manage completed BlendRender scenes, jobs, and results on a RunPod network volume."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from blendrender.runpod_catalog import (
    CatalogScene,
    DeletionSummary,
    catalog_json,
    delete_jobs,
    delete_results,
    delete_scenes,
    download_results,
    format_catalog,
    list_scenes,
)
from blendrender.runpod_scene import (
    DEFAULT_UPLOAD_WORKERS,
    MAX_UPLOAD_WORKERS,
    Boto3Uploader,
    RunpodS3Settings,
    RunpodScenePreparationError,
)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = _create_parser()
    args = parser.parse_args()

    try:
        settings = RunpodS3Settings.from_env()
        if args.command in {"delete-scenes", "delete-jobs", "delete-results"}:
            _require_confirmation(args.confirm, settings)
        upload_workers = getattr(args, "transfer_workers", DEFAULT_UPLOAD_WORKERS)
        uploader = Boto3Uploader(settings, upload_workers=upload_workers)
        scenes = list_scenes(uploader, settings, scene_id=getattr(args, "scene_id", None))
        if args.command == "list":
            _print_catalog(scenes, as_json=args.json)
            return
        if args.command == "download":
            download = download_results(uploader, settings, scenes, args.download_dir)
            print(
                f"Downloaded {download.file_count} files ({download.size_bytes} bytes) to "
                f"{args.download_dir}."
            )
            return
        deletion = _delete_catalog_entries(args, uploader, settings, scenes)
    except RunpodScenePreparationError as exc:
        raise SystemExit(f"RunPod scene management failed: {exc}") from exc

    _print_deletion(deletion)


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage completed BlendRender scenes, jobs, and results on a RunPod network volume."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser("list", help="List completed scenes, jobs, and results")
    list_command.add_argument("--scene-id", help="Only list one completed scene UUID")
    list_command.add_argument("--json", action="store_true", help="Print the catalog as JSON")

    download_command = commands.add_parser("download", help="Download completed result packages")
    download_command.add_argument(
        "--scene-id", help="Only download results for one completed scene UUID"
    )
    download_command.add_argument(
        "--download-dir",
        type=Path,
        required=True,
        metavar="DIRECTORY",
        help="Download result packages into a new or empty directory",
    )
    download_command.add_argument(
        "--transfer-workers",
        type=int,
        default=DEFAULT_UPLOAD_WORKERS,
        metavar="COUNT",
        help=(
            f"Maximum concurrent S3 requests (default: {DEFAULT_UPLOAD_WORKERS}; "
            f"maximum: {MAX_UPLOAD_WORKERS})"
        ),
    )

    _add_delete_command(commands, "delete-scenes", "scene", "scenes")
    _add_delete_command(commands, "delete-jobs", "job", "jobs")
    _add_delete_command(commands, "delete-results", "result", "results")
    return parser


def _add_delete_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    command_name: str,
    entity_kind: str,
    entity_plural: str,
) -> None:
    command = commands.add_parser(command_name, help=f"Delete completed {entity_plural}")
    target = command.add_mutually_exclusive_group(required=True)
    target.add_argument(f"--{entity_kind}-id", help=f"Delete one completed {entity_kind} UUID")
    target.add_argument("--all", action="store_true", help=f"Delete all completed {entity_plural}")
    command.add_argument(
        "--confirm",
        metavar="NETWORK_VOLUME_ID",
        required=True,
        help="Must exactly match RUNPOD_NETWORK_VOLUME_ID",
    )


def _require_confirmation(confirm: str, settings: RunpodS3Settings) -> None:
    if confirm != settings.volume_id:
        raise RunpodScenePreparationError(
            "Refusing to delete catalog data. Re-run with "
            f"--confirm {settings.volume_id}"
        )


def _delete_catalog_entries(
    args: argparse.Namespace,
    uploader: Boto3Uploader,
    settings: RunpodS3Settings,
    scenes: tuple[CatalogScene, ...],
) -> DeletionSummary:
    if args.command == "delete-scenes":
        return delete_scenes(
            uploader,
            settings,
            scenes,
            scene_ids=None if args.all else frozenset({args.scene_id}),
        )
    if args.command == "delete-jobs":
        return delete_jobs(
            uploader,
            settings,
            scenes,
            job_ids=None if args.all else frozenset({args.job_id}),
        )
    if args.command == "delete-results":
        return delete_results(
            uploader,
            scenes,
            result_ids=None if args.all else frozenset({args.result_id}),
        )
    raise AssertionError(f"Unexpected command {args.command}")


def _print_catalog(scenes: tuple[CatalogScene, ...], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(catalog_json(scenes), indent=2, sort_keys=True))
        return
    print(format_catalog(scenes))


def _print_deletion(deletion: DeletionSummary) -> None:
    entity_label = (
        deletion.entity_kind if deletion.entity_count == 1 else f"{deletion.entity_kind}s"
    )
    object_label = "object" if deletion.object_count == 1 else "objects"
    print(
        f"Deleted {deletion.entity_count} {entity_label} and "
        f"{deletion.object_count} {object_label}."
    )


if __name__ == "__main__":
    main()
