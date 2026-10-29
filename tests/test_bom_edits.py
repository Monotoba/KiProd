from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.core.bom import build
from kiprod.core.bom_edits import (
    BOMOverrides,
    apply_bom_overrides,
    load_bom_overrides,
    save_bom_overrides,
)
from kiprod.core.project import discover


def test_bom_mpn_override_is_user_sourced_and_persistent(tmp_path: Path) -> None:
    project_path = Path(__file__).parent / "projects" / "basic"
    bom = build(discover(project_path))
    line = bom.lines[0]
    path = tmp_path / "bom.user-overrides.json"
    overrides = BOMOverrides(mpn={line.line_id: "USER-MPN-1"})

    save_bom_overrides(path, overrides)
    updated = apply_bom_overrides(bom, load_bom_overrides(path))

    changed = next(item for item in updated.lines if item.line_id == line.line_id)
    assert changed.mpn == "USER-MPN-1"
    assert changed.resolved_fields["mpn"].source == "user"


def test_bom_override_can_clear_mpn_and_rejects_unknown_lines(tmp_path: Path) -> None:
    bom = build(discover(Path(__file__).parent / "projects" / "basic"))
    line = bom.lines[0]
    cleared = apply_bom_overrides(bom, BOMOverrides(mpn={line.line_id: None}))
    assert next(item for item in cleared.lines if item.line_id == line.line_id).mpn is None
    with pytest.raises(ValueError, match="unknown line ID"):
        apply_bom_overrides(bom, BOMOverrides(mpn={"unknown": "MPN"}))
