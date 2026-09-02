from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

EVENT_PREFIX = "BR "
SAMPLE_PATTERNS = (
    re.compile(r"Sample\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE),
    re.compile(r"Rendering\s+(\d+)\s*/\s*(\d+)\s+samples", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class ParsedLine:
    event: dict[str, Any] | None = None
    sample_current: int | None = None
    sample_total: int | None = None


def parse_renderer_line(line: str) -> ParsedLine:
    stripped = line.strip()
    if stripped.startswith(EVENT_PREFIX):
        try:
            payload = json.loads(stripped.removeprefix(EVENT_PREFIX))
        except json.JSONDecodeError:
            return ParsedLine()
        return ParsedLine(event=payload if isinstance(payload, dict) else None)
    for pattern in SAMPLE_PATTERNS:
        match = pattern.search(stripped)
        if match:
            current, total = int(match.group(1)), int(match.group(2))
            if total > 0:
                return ParsedLine(sample_current=current, sample_total=total)
    return ParsedLine()


def overall_progress(
    *, completed_count: int, total_frames: int, sample_current: int = 0, sample_total: int = 1
) -> float:
    if total_frames <= 0:
        return 0
    fraction = min(1.0, max(0.0, sample_current / sample_total if sample_total else 0))
    return min(99.9, max(0.0, (completed_count + fraction) / total_frames * 100))


def estimate_remaining_seconds(
    *,
    elapsed_seconds: float,
    completed_count: int,
    total_frames: int,
    sample_current: int = 0,
    sample_total: int = 1,
    frame_average_seconds: float | None = None,
    frame_remaining_seconds: float | None = None,
) -> float | None:
    """Estimate the entire job's remaining duration from the active frame."""
    if total_frames <= completed_count:
        return 0
    if frame_remaining_seconds is None and sample_current > 0 and sample_total > 0:
        fraction = min(1.0, sample_current / sample_total)
        frame_remaining_seconds = elapsed_seconds * (1 - fraction) / fraction
    if frame_remaining_seconds is None:
        return None

    frames_after_current = max(0, total_frames - completed_count - 1)
    estimated_frame_seconds = frame_average_seconds or (elapsed_seconds + frame_remaining_seconds)
    return max(0.0, frame_remaining_seconds + frames_after_current * estimated_frame_seconds)
