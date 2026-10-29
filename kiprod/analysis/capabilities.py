from __future__ import annotations

from pydantic import BaseModel

from kiprod.core.models import BoardSpec
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
