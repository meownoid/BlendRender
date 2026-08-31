#!/usr/bin/env python3
"""Clear every object from a RunPod network volume through its S3 API."""

from __future__ import annotations

import argparse
import logging

from blendrender.runpod_scene import Boto3Uploader, RunpodS3Settings, RunpodScenePreparationError

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description=(
            "Delete every object and incomplete multipart upload from a RunPod network volume."
        )
    )
    parser.add_argument(
        "--confirm",
        metavar="NETWORK_VOLUME_ID",
        help="Required to delete; must exactly match RUNPOD_NETWORK_VOLUME_ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count the objects and incomplete multipart uploads that would be removed",
    )
    args = parser.parse_args()

    try:
        settings = RunpodS3Settings.from_env()
        if not args.dry_run and args.confirm != settings.volume_id:
            raise RunpodScenePreparationError(
                "Refusing to clear the network volume. Re-run with "
                f"--confirm {settings.volume_id}"
            )
        logger.info(
            "Starting %s cleanup for network volume %s",
            "dry-run" if args.dry_run else "destructive",
            settings.volume_id,
        )
        result = Boto3Uploader(settings).clear_volume(dry_run=args.dry_run)
    except RunpodScenePreparationError as exc:
        raise SystemExit(f"Network-volume cleanup failed: {exc}") from exc

    action = "Would delete" if result.dry_run else "Deleted"
    multipart_action = "would abort" if result.dry_run else "aborted"
    print(
        f"{action} {result.deleted_object_count} objects and {multipart_action} "
        f"{result.aborted_multipart_upload_count} incomplete multipart uploads "
        f"from network volume {settings.volume_id}."
    )
    logger.info("Network-volume cleanup finished")


if __name__ == "__main__":
    main()
