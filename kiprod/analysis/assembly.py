from __future__ import annotations

import re
from math import hypot
from pathlib import Path

from kiprod.core.models import AssemblySpec
from kiprod.kicad.sexpr import SExpr, atom, children, load

_PACKAGE_METRIC = re.compile(r"(?:^|[^0-9])(01005|0201|0402|0603|0805|1206|1210|1812)(?:[^0-9]|$)")
_METRIC_MM = {
    "01005": 0.4,
    "0201": 0.6,
    "0402": 1.0,
    "0603": 1.6,
    "0805": 2.0,
    "1206": 3.2,
    "1210": 3.2,
    "1812": 4.5,
}


def _property(footprint: list[SExpr], name: str) -> str:
    for prop in children(footprint, "property"):
        if atom(prop, 1) == name:
            return atom(prop, 2) or ""
    return ""


def extract(path: Path) -> AssemblySpec:
    board = load(path)[0]
    footprints = [item for item in children(board, "footprint") if _property(item, "Reference")]
    top = bottom = smd = through_hole = 0
    sizes: list[float] = []
    bga = qfn = lga = 0
    pitches: list[float] = []
    for footprint in footprints:
        layer_nodes = children(footprint, "layer")
        layer = atom(layer_nodes[0], 1) if layer_nodes else ""
        top += int(layer == "F.Cu")
        bottom += int(layer == "B.Cu")
        attr_nodes = children(footprint, "attr")
        attr = (
            {atom(attr_nodes[0], index) for index in range(1, len(attr_nodes[0]))}
            if attr_nodes
            else set()
        )
        if "through_hole" in attr:
            through_hole += 1
        else:
            smd += 1
        name = atom(footprint, 1) or ""
        match = _PACKAGE_METRIC.search(name)
        if match:
            sizes.append(_METRIC_MM[match.group(1)])
        package_name = name.casefold()
        bga += int("bga" in package_name)
        qfn += int("qfn" in package_name)
        lga += int("lga" in package_name)
        pad_centers: list[tuple[float, float]] = []
        for pad in children(footprint, "pad"):
            at = children(pad, "at")
            if not at:
                continue
            try:
                pad_centers.append((float(atom(at[0], 1) or ""), float(atom(at[0], 2) or "")))
            except ValueError:
                continue
        for index, first in enumerate(pad_centers):
            for second in pad_centers[index + 1 :]:
                distance = hypot(first[0] - second[0], first[1] - second[1])
                if distance > 0:
                    pitches.append(distance)
    return AssemblySpec(
        placement_top=top,
        placement_bottom=bottom,
        unique_parts=len(footprints),
        smd_count=smd,
        through_hole_count=through_hole,
        smallest_package_mm=min(sizes) if sizes else None,
        bga_count=bga,
        qfn_count=qfn,
        lga_count=lga,
        finest_pitch_mm=min(pitches) if pitches else None,
    )
