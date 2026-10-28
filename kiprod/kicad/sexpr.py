from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_TOKEN = re.compile(r'\s*(?:(\()|(\))|("(?:\\.|[^"\\])*")|([^\s()]+))')


@dataclass(frozen=True)
class Atom:
    value: str


SExpr = Atom | list["SExpr"]


def parse(text: str) -> list[SExpr]:
    """Parse the small, quoted-string-aware S-expression subset KiCad uses."""
    roots: list[SExpr] = []
    stack: list[list[SExpr]] = []
    position = 0
    while position < len(text):
        if text[position:].isspace():
            break
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"invalid KiCad S-expression at byte {position}")
        position = match.end()
        if match.group(1):
            node: list[SExpr] = []
            if stack:
                stack[-1].append(node)
            else:
                roots.append(node)
            stack.append(node)
        elif match.group(2):
            if not stack:
                raise ValueError("unexpected closing parenthesis")
            stack.pop()
        else:
            raw = match.group(3) or match.group(4)
            if raw is None:
                continue
            value = bytes(raw[1:-1], "utf-8").decode("unicode_escape") if raw.startswith('"') else raw
            if not stack:
                raise ValueError("atom outside a list")
            stack[-1].append(Atom(value))
    if stack:
        raise ValueError("unclosed parenthesis in KiCad S-expression")
    return roots


def children(node: SExpr, label: str) -> list[list[SExpr]]:
    if not isinstance(node, list):
        return []
    return [child for child in node if isinstance(child, list) and head(child) == label]


def head(node: list[SExpr]) -> str | None:
    return node[0].value if node and isinstance(node[0], Atom) else None


def atom(node: list[SExpr], index: int) -> str | None:
    return node[index].value if len(node) > index and isinstance(node[index], Atom) else None


def walk(node: SExpr) -> list[list[SExpr]]:
    found: list[list[SExpr]] = []
    if isinstance(node, list):
        found.append(node)
        for child in node:
            found.extend(walk(child))
    return found


def load(path: Path) -> list[SExpr]:
    return parse(path.read_text(encoding="utf-8"))
