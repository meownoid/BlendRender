from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

EVENT_PREFIX = "BLENDRENDER_EVENT "
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
