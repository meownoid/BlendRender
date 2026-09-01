"""Enable the trusted FLIP Fluids add-on before an uploaded scene is opened."""

from __future__ import annotations

import os

import addon_utils


def run() -> None:
    module = os.getenv("FLIP_FLUIDS_ADDON", "").strip()
    if not module:
        raise RuntimeError("FLIP_FLUIDS_ADDON is required when running the FLIP Fluids bootstrap")

    addon_utils.modules_refresh()
    _, loaded = addon_utils.check(module)
    if not loaded:
        addon_utils.enable(module, default_set=False, persistent=False)
    _, loaded = addon_utils.check(module)
    if not loaded:
        raise RuntimeError(f"Unable to enable bundled Blender add-on: {module}")
    print(f"BLENDRENDER_FLIP_FLUIDS enabled {module}", flush=True)


run()
