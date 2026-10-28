from __future__ import annotations

import csv
from pathlib import Path

from kiprod.core.models import NormalizedBOM


def write_bom(bom: NormalizedBOM, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "bom.normalized.json"
    csv_path = output_dir / "bom.csv"
    json_path.write_text(bom.model_dump_json(indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["references", "quantity", "value", "footprint", "mpn"])
        writer.writeheader()
        for line in bom.lines:
            writer.writerow(
                {
                    "references": ", ".join(line.references),
                    "quantity": line.quantity,
                    "value": line.value,
                    "footprint": line.footprint,
                    "mpn": line.mpn or "",
                }
            )
    return json_path, csv_path
