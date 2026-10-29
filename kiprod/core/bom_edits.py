from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import NormalizedBOM, ResolvedField


class BOMOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    mpn: dict[str, str | None] = Field(default_factory=dict)


def apply_bom_overrides(bom: NormalizedBOM, overrides: BOMOverrides) -> NormalizedBOM:
    lines = {line.line_id: line for line in bom.lines}
    unknown = sorted(set(overrides.mpn) - lines.keys())
    if unknown:
        raise ValueError("BOM override references unknown line ID(s): " + ", ".join(unknown))
    updated = []
    for line in bom.lines:
        if line.line_id not in overrides.mpn:
            updated.append(line)
            continue
        value = overrides.mpn[line.line_id]
        resolved = dict(line.resolved_fields)
        if value is None:
            resolved.pop("mpn", None)
        else:
            resolved["mpn"] = ResolvedField(value=value, source="user")
        updated.append(line.model_copy(update={"mpn": value, "resolved_fields": resolved}))
    return bom.model_copy(update={"lines": updated})


def load_bom_overrides(path: Path) -> BOMOverrides:
    if not path.is_file():
        return BOMOverrides()
    return BOMOverrides.model_validate_json(path.read_text(encoding="utf-8"))


def save_bom_overrides(path: Path, overrides: BOMOverrides) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(overrides.model_dump_json(indent=2) + "\n")
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
