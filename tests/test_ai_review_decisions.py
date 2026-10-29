from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.ai.review import ReviewFinding
from kiprod.ai.review_decisions import (
    latest_dispositions,
    load_decisions,
    record_decision,
)


def _finding() -> ReviewFinding:
    return ReviewFinding(
        code="bom.check_mpn",
        severity="warning",
        area="bom",
        summary="Verify the selected part.",
        confidence=0.7,
        source="ai_guess",
        line_ids=["abc123"],
        evidence=[],
    )


def test_review_dispositions_are_append_only_and_latest_is_visible(tmp_path: Path) -> None:
    path = tmp_path / "review.decisions.json"
    finding = _finding()

    record_decision(path, finding, "defer", "Need the supplier datasheet.")
    updated = record_decision(path, finding, "accept", "Confirmed against the schematic.")

    assert len(updated.decisions) == 2
    assert latest_dispositions(updated)[updated.decisions[0].finding_key] == "accept"
    assert load_decisions(path) == updated


def test_review_reject_or_defer_requires_a_comment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="comment is required"):
        record_decision(tmp_path / "decisions.json", _finding(), "dismiss", " ")


def test_invalid_decision_file_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError):
        record_decision(path, _finding(), "accept", "")

    assert path.read_text(encoding="utf-8") == "not-json"
