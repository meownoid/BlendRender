from __future__ import annotations

import errno
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

ARCHIVE_COPY_CHUNK_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
ArchiveHeartbeat = Callable[[], None]


class ProjectArchiveError(ValueError):
    """Raised when a ZIP cannot safely represent a BlendRender project."""


class ProjectArchiveCapacityError(ProjectArchiveError):
    """Raised when extraction runs out of data-disk capacity."""


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    target: Path
    is_directory: bool
    size: int


@dataclass(frozen=True, slots=True)
class ProjectArchiveManifest:
    source_root: Path
    entries: tuple[ArchiveEntry, ...]
    scene_path: Path
    total_size: int

    @property
    def scene_relative_path(self) -> Path:
        return self.scene_path.relative_to(self.source_root)


def inspect_project_archive(
    archive_path: Path,
    source_root: Path,
    max_size: int,
    heartbeat: ArchiveHeartbeat | None = None,
) -> ProjectArchiveManifest:
    """Validate a ZIP and return the extraction plan without writing any project files."""
    root = source_root.resolve()
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            infos = bundle.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectArchiveError("The uploaded ZIP archive is invalid") from exc

    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ProjectArchiveError(f"ZIP archives may contain at most {MAX_ARCHIVE_MEMBERS} entries")

    entries: list[ArchiveEntry] = []
    targets: dict[Path, ArchiveEntry] = {}
    scenes: list[Path] = []
    total_size = 0
    for index, info in enumerate(infos, start=1):
        if heartbeat is not None and index % 100 == 0:
            heartbeat()
        entry = _archive_entry(info, root)
        if entry.target in targets:
            raise ProjectArchiveError("ZIP archive contains duplicate paths")
        targets[entry.target] = entry
        entries.append(entry)
        if not entry.is_directory:
            total_size += entry.size
            if total_size > max_size:
                raise ProjectArchiveError("ZIP archive expands beyond the configured upload limit")
            if entry.target.suffix.lower() == ".blend":
                scenes.append(entry.target)

    _validate_target_hierarchy(entries, root)
    if len(scenes) != 1:
        raise ProjectArchiveError("ZIP archives must contain exactly one .blend file")
    return ProjectArchiveManifest(root, tuple(entries), scenes[0], total_size)


def extract_project_archive(
    archive_path: Path,
    source_root: Path,
    manifest: ProjectArchiveManifest,
    max_size: int,
    heartbeat: ArchiveHeartbeat | None = None,
) -> None:
    """Extract a previously validated manifest, checking actual decompressed bytes as it copies."""
    copied_total = 0
    try:
        source_root.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive_path) as bundle:
            for entry in manifest.entries:
                if heartbeat is not None:
                    heartbeat()
                if entry.is_directory:
                    entry.target.mkdir(parents=True, exist_ok=True)
                    continue
                entry.target.parent.mkdir(parents=True, exist_ok=True)
                copied_entry = 0
                with bundle.open(entry.name) as source, entry.target.open("xb") as destination:
                    while chunk := source.read(ARCHIVE_COPY_CHUNK_BYTES):
                        if heartbeat is not None:
                            heartbeat()
                        copied_entry += len(chunk)
                        copied_total += len(chunk)
                        if copied_total > max_size:
                            raise ProjectArchiveError(
                                "ZIP archive expands beyond the configured upload limit"
                            )
                        destination.write(chunk)
                if copied_entry != entry.size:
                    raise ProjectArchiveError("ZIP archive entry size did not match its metadata")
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise ProjectArchiveCapacityError(
                "Insufficient disk space to extract the uploaded ZIP archive"
            ) from exc
        raise ProjectArchiveError("The uploaded ZIP archive could not be extracted") from exc
    except (NotImplementedError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ProjectArchiveError("The uploaded ZIP archive could not be extracted") from exc


def _archive_entry(info: zipfile.ZipInfo, root: Path) -> ArchiveEntry:
    name = info.filename
    if not name or "\x00" in name:
        raise ProjectArchiveError("ZIP archive contains an invalid path")
    if info.flag_bits & 0x1:
        raise ProjectArchiveError("Encrypted ZIP archives are not supported")
    if "\\" in name or PureWindowsPath(name).drive or PureWindowsPath(name).is_absolute():
        raise ProjectArchiveError("ZIP archive contains an absolute path")

    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise ProjectArchiveError("ZIP archive contains an unsafe path")
    target = (root.joinpath(*relative.parts)).resolve()
    if not target.is_relative_to(root):
        raise ProjectArchiveError("ZIP archive contains an unsafe path")

    mode = info.external_attr >> 16
    is_directory = info.is_dir() or stat.S_ISDIR(mode)
    file_type = stat.S_IFMT(mode)
    if not is_directory and file_type not in {0, stat.S_IFREG}:
        raise ProjectArchiveError("ZIP archives may contain only regular files and directories")
    if info.file_size < 0:
        raise ProjectArchiveError("ZIP archive contains an invalid file size")
    return ArchiveEntry(name=name, target=target, is_directory=is_directory, size=info.file_size)


def _validate_target_hierarchy(entries: list[ArchiveEntry], root: Path) -> None:
    file_targets = {entry.target for entry in entries if not entry.is_directory}
    for entry in entries:
        for parent in entry.target.parents:
            if parent == root:
                break
            if parent in file_targets:
                raise ProjectArchiveError(
                    "ZIP archive contains conflicting file and directory paths"
                )
