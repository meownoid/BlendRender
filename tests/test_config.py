from __future__ import annotations

import pytest
from blendrender.config import Settings


def test_upload_chunk_size_defaults_to_eight_mebibytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.delenv("UPLOAD_CHUNK_MB", raising=False)

    assert Settings.from_env().upload_chunk_bytes == 8 * 1024**2


def test_upload_chunk_size_uses_configured_mebibytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("UPLOAD_CHUNK_MB", "4")

    assert Settings.from_env().upload_chunk_bytes == 4 * 1024**2


def test_flip_fluids_addon_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.delenv("FLIP_FLUIDS_ADDON", raising=False)

    settings = Settings.from_env()

    assert settings.flip_fluids_addon is None
    assert settings.flip_fluids_bootstrap_script is None


def test_flip_fluids_addon_uses_the_bundled_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("FLIP_FLUIDS_ADDON", "flip_fluids_addon")

    settings = Settings.from_env()

    assert settings.flip_fluids_addon == "flip_fluids_addon"
    assert settings.flip_fluids_bootstrap_script is not None
    assert settings.flip_fluids_bootstrap_script.name == "blendrender_enable_flip_fluids.py"


@pytest.mark.parametrize("value", ["../flip_fluids_addon", "flip-fluids", "123addon"])
def test_flip_fluids_addon_rejects_an_invalid_module_name(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("FLIP_FLUIDS_ADDON", value)

    with pytest.raises(RuntimeError, match="FLIP_FLUIDS_ADDON must be a valid Python module name"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_upload_chunk_size_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("UPLOAD_CHUNK_MB", value)

    with pytest.raises(RuntimeError, match="UPLOAD_CHUNK_MB must be a positive whole number"):
        Settings.from_env()
