from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.rfq.offer_review import (
    latest_offer_decisions,
    load_offer_decisions,
    record_offer_decision,
)
from kiprod.rfq.quote_import import ExtractedOffer


def _candidate() -> ExtractedOffer:
    return ExtractedOffer(
        offer=Offer(
            supplier_id="supplier-a",
            supplier_part_number="SKU-1",
            manufacturer_part_number="MPN-1",
            price_breaks=[PriceBreak(quantity=10, unit_price=1.25, currency="USD")],
            source_ref=SourceRef(path="reply.csv", reference="row:2"),
        ),
        confidence=0.7,
        requires_review=True,
    )


def test_offer_review_appends_confirm_and_correction_events(tmp_path: Path) -> None:
    path = tmp_path / "review.decisions.json"
    candidate = _candidate()
    corrected = candidate.offer.model_copy(update={"manufacturer_part_number": "MPN-CORRECT"})
    first = record_offer_decision(
        path,
        supplier_id="supplier-a",
        source_file="offers.json",
        index=0,
        candidate=candidate,
        disposition="confirmed",
    )
    updated = record_offer_decision(
        path,
        supplier_id="supplier-a",
        source_file="offers.json",
        index=0,
        candidate=candidate,
        disposition="corrected",
        corrected_offer=corrected,
        comment="Verified against supplier quote.",
    )

    assert len(first.decisions) == 1
    assert len(updated.decisions) == 2
    assert updated.decisions[-1].corrected_offer == corrected
    assert (
        latest_offer_decisions(load_offer_decisions(path))[
            updated.decisions[-1].candidate_key
        ].disposition
        == "corrected"
    )


def test_offer_review_requires_comments_and_preserves_source_ref(tmp_path: Path) -> None:
    arguments = {
        "supplier_id": "supplier-a",
        "source_file": "offers.json",
        "index": 0,
        "candidate": _candidate(),
    }
    with pytest.raises(ValueError, match="comment is required"):
        record_offer_decision(
            tmp_path / "decisions.json", **arguments, disposition="rejected", comment=" "
        )
    unrelated_source = _candidate().offer.model_copy(
        update={"source_ref": SourceRef(path="other.csv", reference="row:4")}
    )
    with pytest.raises(ValueError, match="retain the original source reference"):
        record_offer_decision(
            tmp_path / "decisions.json",
            **arguments,
            disposition="corrected",
            corrected_offer=unrelated_source,
            comment="Should not change evidence.",
        )
