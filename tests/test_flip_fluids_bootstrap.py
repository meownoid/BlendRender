from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path


class FakeMaterialLibrary:
    def __init__(self) -> None:
        self.library_path = "/Users/artist/Library/Application Support/Blender/material_library"
        self.initialized_paths: list[str] = []
        self.original_check_calls = 0

    def initialize(self, library_path: str) -> None:
        self.library_path = library_path
        self.initialized_paths.append(library_path)

    def check_icons_initialized(self) -> None:
        self.original_check_calls += 1

    def _generate_material_library_icons(self) -> None:
        pass


class FakeLibraries(list[object]):
    def remove(self, library: object, *, do_unlink: bool) -> None:
        assert not do_unlink
        super().remove(library)


def test_flip_fluids_bootstrap_replaces_a_scene_saved_material_library_path(
    monkeypatch,
) -> None:
    script = Path(__file__).parents[1] / "renderer" / "blendrender_enable_flip_fluids.py"
    library = FakeMaterialLibrary()
    handlers = types.SimpleNamespace(load_post=[], persistent=lambda handler: handler)
    bundled_library = types.SimpleNamespace(
        filepath=(
            "/opt/blender/5.2/scripts/addons_core/flip_fluids_addon/materials/"
            "material_library/surface/FF Apple Juice.blend"
        )
    )
    scene_library = types.SimpleNamespace(filepath="/tmp/project/scene_library.blend")
    data_libraries = FakeLibraries([bundled_library, scene_library])
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(handlers=handlers)
    bpy.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(flip_fluid_material_library=library)
    )
    bpy.data = types.SimpleNamespace(libraries=data_libraries)
    bpy.path = types.SimpleNamespace(abspath=lambda filepath: filepath)

    addon_utils = types.ModuleType("addon_utils")
    loaded = False
    enabled: list[tuple[str, bool, bool]] = []

    def check(_: str) -> tuple[bool, bool]:
        return True, loaded

    def enable(module: str, *, default_set: bool, persistent: bool) -> None:
        nonlocal loaded
        enabled.append((module, default_set, persistent))
        loaded = True

    addon_utils.modules_refresh = lambda: None
    addon_utils.check = check
    addon_utils.enable = enable

    addon = types.ModuleType("flip_fluids_addon")
    addon.__path__ = []
    materials = types.ModuleType("flip_fluids_addon.materials")
    materials.__path__ = []
    material_library = types.ModuleType("flip_fluids_addon.materials.material_library")
    material_library.__file__ = (
        "/opt/blender/5.2/scripts/addons_core/flip_fluids_addon/materials/material_library.py"
    )
    material_library_objects = types.ModuleType(
        "flip_fluids_addon.objects.flip_fluid_material_library"
    )
    material_library_objects.FLIPFluidMaterialLibrary = FakeMaterialLibrary
    objects = types.ModuleType("flip_fluids_addon.objects")
    objects.__path__ = []
    addon.materials = materials
    addon.objects = objects
    materials.material_library = material_library
    objects.flip_fluid_material_library = material_library_objects

    monkeypatch.setenv("FLIP_FLUIDS_ADDON", "flip_fluids_addon")
    for name, module in {
        "addon_utils": addon_utils,
        "bpy": bpy,
        "flip_fluids_addon": addon,
        "flip_fluids_addon.materials": materials,
        "flip_fluids_addon.materials.material_library": material_library,
        "flip_fluids_addon.objects": objects,
        "flip_fluids_addon.objects.flip_fluid_material_library": material_library_objects,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    runpy.run_path(str(script))

    expected_path = (
        "/opt/blender/5.2/scripts/addons_core/flip_fluids_addon/materials/material_library"
    )
    assert enabled == [("flip_fluids_addon", True, False)]
    assert len(handlers.load_post) == 1

    library.check_icons_initialized()
    assert library.initialized_paths == [expected_path]
    assert library.original_check_calls == 0

    library.check_icons_initialized()
    assert library.original_check_calls == 1

    library._generate_material_library_icons()
    assert data_libraries == [scene_library]

    library.library_path = "/Users/artist/Library/Application Support/Blender/material_library"
    handlers.load_post[0](None)
    assert library.initialized_paths == [expected_path, expected_path]
