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
    main_schematic: Path
    schematics: list[Path]
    boards: list[Path]
    variants: list[str] = Field(default_factory=list)
    input_hashes: dict[str, str]


class BoardSpec(BaseModel):
    source: str
    layers: int
    thickness_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    min_track_mm: float | None = None
    min_drill_mm: float | None = None
    copper_finish: str | None = None
    stackup: list[dict[str, str | float]] = Field(default_factory=list)


class Placement(BaseModel):
    reference: str
    value: str = ""
    footprint: str = ""
    x_mm: float
    y_mm: float
    side: str
    rotation: float


class AssemblySpec(BaseModel):
    placement_top: int
    placement_bottom: int
    unique_parts: int
    smd_count: int
    through_hole_count: int
    smallest_package_mm: float | None = None
    bga_count: int = 0
    qfn_count: int = 0
    lga_count: int = 0
    finest_pitch_mm: float | None = None


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
    resolved_fields: dict[str, ResolvedField] = Field(default_factory=dict)
    sources: list[SourceRef]


class NormalizedBOM(BaseModel):
    schema_version: int = 1
    project: str
    input_hashes: dict[str, str]
    lines: list[BOMLine]
    imported_bom: str | None = None


class ResolvedField(BaseModel):
    value: str
    source: str


class PriceBreak(BaseModel):
    quantity: int
    unit_price: float
    currency: str


class Offer(BaseModel):
    supplier_id: str
    supplier_part_number: str
    manufacturer_part_number: str
    price_breaks: list[PriceBreak]
    stock: int | None = None
    lead_time_days: int | None = None
    source_ref: SourceRef
