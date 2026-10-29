from __future__ import annotations

from pathlib import Path

from kiprod.core.models import BoardSpec
from kiprod.kicad.sexpr import Atom, SExpr, atom, children, head, load


def _number(node: list[SExpr], label: str) -> float | None:
    values = children(node, label)
    if not values:
        return None
    raw = atom(values[0], 1)
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _walk(node: SExpr) -> list[list[SExpr]]:
    found: list[list[SExpr]] = []
    if isinstance(node, list):
        found.append(node)
        for child in node:
            found.extend(_walk(child))
    return found


def _edge_points(nodes: list[list[SExpr]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for node in nodes:
        if head(node) == "gr_line" and children(node, "layer"):
            layer = atom(children(node, "layer")[0], 1)
            if layer != "Edge.Cuts":
                continue
            for label in ("start", "end"):
                coordinates = children(node, label)
                if coordinates:
                    try:
                        x, y = (
                            float(atom(coordinates[0], 1) or ""),
                            float(atom(coordinates[0], 2) or ""),
                        )
                        points.append((x, y))
                    except ValueError:
                        continue
    return points


def extract(path: Path) -> BoardSpec:
    roots = load(path)
    board = roots[0] if roots else []
    nodes = _walk(board)
    layer_tables = children(board, "layers")
    copper_layers = 0
    if layer_tables:
        for layer in layer_tables[0]:
            if isinstance(layer, list) and len(layer) > 1 and isinstance(layer[1], Atom):
                if layer[1].value.endswith(".Cu"):
                    copper_layers += 1
    general = children(board, "general")
    thickness = _number(general[0], "thickness") if general else None
    points = _edge_points(nodes)
    width = max((point[0] for point in points), default=0) - min(
        (point[0] for point in points), default=0
    )
    height = max((point[1] for point in points), default=0) - min(
        (point[1] for point in points), default=0
    )
    setup = children(board, "setup")
    return BoardSpec(
        source=path.name,
        layers=copper_layers,
        thickness_mm=thickness,
        width_mm=width if points else None,
        height_mm=height if points else None,
        min_track_mm=_number(setup[0], "min_track_width") if setup else None,
        min_drill_mm=_number(setup[0], "min_via_drill") if setup else None,
    )
