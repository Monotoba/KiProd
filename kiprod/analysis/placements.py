from __future__ import annotations

import csv
from pathlib import Path

from kiprod.core.models import Placement

_FIELDS = {
    "reference": lambda item: item.reference,
    "designator": lambda item: item.reference,
    "value": lambda item: item.value,
    "footprint": lambda item: item.footprint,
    "x": lambda item: item.x_mm,
    "x_mm": lambda item: item.x_mm,
    "mid x": lambda item: item.x_mm,
    "y": lambda item: item.y_mm,
    "y_mm": lambda item: item.y_mm,
    "mid y": lambda item: item.y_mm,
    "side": lambda item: item.side,
    "layer": lambda item: item.side,
    "rotation": lambda item: item.rotation,
}


def write_placements(placements: list[Placement], columns: list[str], output: Path) -> Path:
    """Write placement rows using the requested assembler column labels."""
    fields = [(label, _FIELDS.get(label.strip().casefold())) for label in columns]
    unknown = [label for label, getter in fields if getter is None]
    if unknown:
        raise ValueError(f"unsupported placement field mapping: {', '.join(unknown)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for placement in placements:
            writer.writerow([getter(placement) for _, getter in fields if getter is not None])
    return output
