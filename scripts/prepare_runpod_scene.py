#!/usr/bin/env python3
"""Upload a BlendRender scene to a RunPod network volume before a Pod starts."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from blendrender.runpod_scene import (
    Boto3Uploader,
    RunpodS3Settings,
    RunpodScenePreparationError,
    prepare_scene,
)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a .blend file or project ZIP in BlendRender's RunPod network-volume workspace."
        )
    )
    parser.add_argument("scene", type=Path, help="Local .blend file or project ZIP")
    parser.add_argument(
        "--name", help="Scene name shown in BlendRender (defaults to the local filename)"
    )
    parser.add_argument(
        "--scene-id",
        help=(
            "UUID to use for the scene (defaults to a new UUID); reuse an interrupted run's UUID "
            "to skip files that finished uploading"
        ),
    )
    args = parser.parse_args()

    try:
        settings = RunpodS3Settings.from_env()
        prepared = prepare_scene(
            args.scene,
            settings,
            Boto3Uploader(settings),
            scene_id=args.scene_id,
            scene_name=args.name,
        )
    except RunpodScenePreparationError as exc:
        raise SystemExit(f"Scene preparation failed: {exc}") from exc

    print(f"Prepared scene {prepared.id} ({prepared.name}); entrypoint: {prepared.entrypoint}")


if __name__ == "__main__":
    main()
