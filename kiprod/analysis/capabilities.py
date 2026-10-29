from __future__ import annotations

from pydantic import BaseModel

from kiprod.core.models import AssemblySpec, BoardSpec
from kiprod.plugins.models import Manifest


class CapabilityFinding(BaseModel):
    field: str
    required: float
    limit: float
    message: str


def check_board(board: BoardSpec, manifest: Manifest) -> list[CapabilityFinding]:
    """Compare extracted fab metrics to numeric limits declared in a plugin manifest."""
    capabilities = manifest.capabilities.get("pcb_fab", {})
    if not isinstance(capabilities, dict):
        return []
    limits = capabilities.get("limits", {})
    if not isinstance(limits, dict):
        return []
    findings: list[CapabilityFinding] = []
    for key, required, label in (
        ("min_track_mm", board.min_track_mm, "minimum track width"),
        ("min_drill_mm", board.min_drill_mm, "minimum drill diameter"),
    ):
        limit = limits.get(key)
        if required is not None and isinstance(limit, (int, float)) and required < limit:
            findings.append(
                CapabilityFinding(
                    field=key,
                    required=required,
                    limit=float(limit),
                    message=f"{label} {required:g} mm is below supplier minimum {limit:g} mm",
                )
            )
    layer_limit = limits.get("layers")
    if board.layers and isinstance(layer_limit, list) and len(layer_limit) == 2:
        minimum, maximum = layer_limit
        if (
            isinstance(minimum, (int, float))
            and isinstance(maximum, (int, float))
            and not minimum <= board.layers <= maximum
        ):
            findings.append(
                CapabilityFinding(
                    field="layers",
                    required=float(board.layers),
                    limit=float(maximum),
                    message=(
                        f"{board.layers} copper layers are outside supplier range "
                        f"{minimum}–{maximum}"
                    ),
                )
            )
    return findings


def check_assembly(assembly: AssemblySpec, manifest: Manifest) -> list[CapabilityFinding]:
    capabilities = manifest.capabilities.get("pcb_assembly", {})
    if not isinstance(capabilities, dict):
        return []
    limits = capabilities.get("limits", {})
    if not isinstance(limits, dict):
        return []
    findings: list[CapabilityFinding] = []
    for key, required, label in (
        (
            "placements_per_side",
            max(assembly.placement_top, assembly.placement_bottom),
            "placements per side",
        ),
        ("unique_parts", assembly.unique_parts, "unique parts"),
    ):
        maximum = limits.get(key)
        if isinstance(maximum, (int, float)) and required > maximum:
            findings.append(
                CapabilityFinding(
                    field=key,
                    required=float(required),
                    limit=float(maximum),
                    message=f"{label} {required} exceeds supplier limit {maximum}",
                )
            )
    min_pitch = limits.get("min_pitch_mm")
    if (
        assembly.finest_pitch_mm is not None
        and isinstance(min_pitch, (int, float))
        and assembly.finest_pitch_mm < min_pitch
    ):
        findings.append(
            CapabilityFinding(
                field="min_pitch_mm",
                required=assembly.finest_pitch_mm,
                limit=float(min_pitch),
                message=(
                    f"finest pitch {assembly.finest_pitch_mm:g} mm is below supplier "
                    f"minimum {min_pitch:g} mm"
                ),
            )
        )
    for package, count in (
        ("bga", assembly.bga_count),
        ("qfn", assembly.qfn_count),
        ("lga", assembly.lga_count),
    ):
        supported = limits.get(f"supports_{package}")
        if count and supported is False:
            findings.append(
                CapabilityFinding(
                    field=f"supports_{package}",
                    required=float(count),
                    limit=0.0,
                    message=(
                        f"board has {count} {package.upper()} package(s), unsupported by supplier"
                    ),
                )
            )
    programming_supported = limits.get("supports_programming")
    if assembly.programming_components and programming_supported is False:
        findings.append(
            CapabilityFinding(
                field="supports_programming",
                required=float(len(assembly.programming_components)),
                limit=0.0,
                message=(
                    f"{len(assembly.programming_components)} component(s) require programming, "
                    "unsupported by supplier"
                ),
            )
        )
    return findings
