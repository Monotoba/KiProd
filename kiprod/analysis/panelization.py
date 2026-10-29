from __future__ import annotations

import re
from pathlib import Path

_PANEL_PATTERNS = (
    re.compile(r"\bboards\s+per\s+panel\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)\s+boards\s+per\s+panel\b", re.IGNORECASE),
)


def extract_boards_per_panel(paths: list[Path]) -> tuple[int | None, str | None]:
    """Read an explicit board count from supplied fabrication-note text files."""
    values: list[tuple[int, Path]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in _PANEL_PATTERNS:
            values.extend((int(match.group(1)), path) for match in pattern.finditer(text))
    distinct = {value for value, _ in values}
    if len(distinct) > 1:
        details = ", ".join(f"{path}: {value}" for value, path in values)
        raise ValueError(f"conflicting boards-per-panel values in fabrication notes: {details}")
    if not values:
        return None, None
    value, path = values[0]
    if value <= 0:
        raise ValueError(f"boards per panel must be a positive integer in {path}")
    return value, str(path)
