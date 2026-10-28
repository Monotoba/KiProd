from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Where a value originated; retained in every durable artifact."""

    path: str
    reference: str | None = None


class Project(BaseModel):
    root: Path
    pro_file: Path
    schematics: list[Path]
    boards: list[Path]
    input_hashes: dict[str, str]


class Part(BaseModel):
    reference: str
    value: str = ""
    footprint: str = ""
    mpn: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    source: SourceRef


class BOMLine(BaseModel):
    line_id: str
    references: list[str]
    quantity: int
    value: str
    footprint: str
    mpn: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    sources: list[SourceRef]


class NormalizedBOM(BaseModel):
    schema_version: int = 1
    project: str
    input_hashes: dict[str, str]
    lines: list[BOMLine]
