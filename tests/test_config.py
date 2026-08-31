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


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_upload_chunk_size_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("UPLOAD_CHUNK_MB", value)

    with pytest.raises(RuntimeError, match="UPLOAD_CHUNK_MB must be a positive whole number"):
        Settings.from_env()
