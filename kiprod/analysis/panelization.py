from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_PANEL_PATTERNS = (
    re.compile(r"\bboards\s+per\s+panel\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)\s+boards\s+per\s+panel\b", re.IGNORECASE),
)

_NOTE_EXTENSIONS = {".md", ".rst", ".txt", ".pdf"}
_NOTE_NAME = re.compile(r"(?:fab|fabrication|panel)", re.IGNORECASE)


def discover_fabrication_notes(root: Path) -> list[Path]:
    """Find text and PDF notes with fabrication or panelization in their filename."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in _NOTE_EXTENSIONS
        and _NOTE_NAME.search(path.stem)
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _read_note(path: Path) -> str:
    if path.suffix.casefold() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    executable = shutil.which("pdftotext")
    if executable is None:
        raise RuntimeError("pdftotext is required to read PDF fabrication notes")
    try:
        result = subprocess.run(
            [executable, "-layout", str(path), "-"],
            capture_output=True,
            check=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"could not extract text from fabrication PDF {path}: {exc}") from exc
    return result.stdout


def extract_boards_per_panel(paths: list[Path]) -> tuple[int | None, str | None]:
    """Read an explicit board count from fabrication-note text or PDF files."""
    values: list[tuple[int, Path]] = []
    for path in paths:
        text = _read_note(path)
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
