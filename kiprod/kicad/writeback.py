from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kiprod.kicad.sexpr import atom, children, parse


@dataclass(frozen=True)
class SchematicFieldUpdate:
    path: Path
    reference: str
    field: str
    value: str


@dataclass(frozen=True)
class WritebackChange:
    path: Path
    reference: str
    field: str
    before: str
    after: str


@dataclass(frozen=True)
class WritebackPlan:
    changes: list[WritebackChange]
    originals: dict[Path, str]
    rendered: dict[Path, str]


def _list_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            stack.append(index)
        elif char == ")":
            if not stack:
                raise ValueError("unexpected closing parenthesis in schematic")
            start = stack.pop()
            spans.append((start, index + 1))
    if quoted or stack:
        raise ValueError("unclosed string or list in schematic")
    return spans


def _symbol_span(text: str, reference: str) -> tuple[int, int] | None:
    for start, end in _list_spans(text):
        snippet = text[start:end]
        if not re.match(r"\(\s*symbol\b", snippet):
            continue
        parsed = parse(snippet)
        if not parsed or not isinstance(parsed[0], list):
            continue
        symbol = parsed[0]
        if not children(symbol, "lib_id"):
            continue
        if any(
            atom(prop, 2) == reference
            for prop in children(symbol, "property")
            if atom(prop, 1) == "Reference"
        ):
            return start, end
    return None


def _field_value(symbol_text: str, field: str) -> str | None:
    parsed = parse(symbol_text)
    if not parsed or not isinstance(parsed[0], list):
        return None
    for prop in children(parsed[0], "property"):
        if atom(prop, 1) == field:
            return atom(prop, 2) or ""
    return None


def _update_field(symbol_text: str, field: str, value: str) -> tuple[str, str, str]:
    aliases = {
        "MPN": ("MPN", "Manufacturer Part Number"),
        "Supplier Part Number": ("Supplier Part Number", "Supplier PN", "SPN"),
    }
    actual_field = next(
        (
            name
            for name in aliases.get(field, (field,))
            if _field_value(symbol_text, name) is not None
        ),
        field,
    )
    before = _field_value(symbol_text, actual_field)
    if before == value:
        return symbol_text, before or "", actual_field
    quoted_field = json.dumps(actual_field, ensure_ascii=False)
    quoted_value = json.dumps(value, ensure_ascii=False)
    pattern = re.compile(r"\(property\s+" + re.escape(quoted_field) + r"\s+\"(?:\\.|[^\"\\])*\"")
    match = pattern.search(symbol_text)
    if match:
        value_start = match.start()
        remainder = symbol_text[value_start : match.end()]
        field_match = re.match(r"\(property\s+\"(?:\\.|[^\"\\])*\"\s+", remainder)
        if field_match is None:
            raise ValueError(f"could not locate value for schematic field {field}")
        start = value_start + field_match.end()
        value_end = match.end()
        updated = symbol_text[:start] + quoted_value + symbol_text[value_end:]
    else:
        prop = (
            f"(property {quoted_field} {quoted_value} (at 0 0 0) "
            "(effects (font (size 1.27 1.27)) (hide yes)))"
        )
        closing = symbol_text.rfind(")")
        if closing < 0:
            raise ValueError("invalid placed symbol expression")
        updated = symbol_text[:closing] + "\n\t\t\t" + prop + symbol_text[closing:]
    parse(updated)
    return updated, before or "", actual_field


def _backup_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".kiprod.bak")
    index = 1
    while candidate.exists():
        candidate = path.with_name(path.name + f".kiprod.bak.{index}")
        index += 1
    return candidate


def _atomic_write(path: Path, content: str) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def prepare_writeback(project_root: Path, updates: list[SchematicFieldUpdate]) -> WritebackPlan:
    """Validate and preview proposed custom-field changes without writing files."""
    root = project_root.resolve()
    grouped: dict[Path, list[SchematicFieldUpdate]] = {}
    for update in updates:
        path = update.path.resolve()
        if path.suffix.casefold() != ".kicad_sch" or not path.is_relative_to(root):
            raise ValueError(f"write-back path is outside the project schematics: {update.path}")
        if not path.is_file():
            raise ValueError(f"schematic does not exist: {path}")
        grouped.setdefault(path, []).append(update)

    changes: list[WritebackChange] = []
    rendered: dict[Path, str] = {}
    originals: dict[Path, str] = {}
    for path, path_updates in grouped.items():
        original = path.read_text(encoding="utf-8")
        originals[path] = original
        content = original
        for update in path_updates:
            span = _symbol_span(content, update.reference)
            if span is None:
                raise ValueError(f"could not locate placed symbol {update.reference} in {path}")
            start, end = span
            symbol_text, before, actual_field = _update_field(
                content[start:end], update.field, update.value
            )
            content = content[:start] + symbol_text + content[end:]
            if before != update.value:
                changes.append(
                    WritebackChange(path, update.reference, actual_field, before, update.value)
                )
        if content != original:
            parse(content)
            rendered[path] = content
    return WritebackPlan(changes, originals, rendered)


def apply_writeback(project_root: Path, plan: WritebackPlan) -> list[Path]:
    """Apply a previously reviewed plan if no source schematic changed since preview."""
    root = project_root.resolve()
    for path, original in plan.originals.items():
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"write-back path is outside the project schematics: {path}")
        if path.read_text(encoding="utf-8") != original:
            raise ValueError(f"schematic changed after write-back preview: {path}")
    if not plan.rendered:
        return []
    backups: dict[Path, Path] = {}
    try:
        for path in plan.rendered:
            backup = _backup_path(path)
            shutil.copy2(path, backup)
            backups[path] = backup
        for path, content in plan.rendered.items():
            _atomic_write(path, content)
    except Exception:
        for path, backup in backups.items():
            if backup.is_file():
                shutil.copy2(backup, path)
        raise
    return list(backups.values())


def writeback_fields(
    project_root: Path, updates: list[SchematicFieldUpdate]
) -> tuple[list[WritebackChange], list[Path]]:
    """Apply field changes and preserve originals as unique backups."""
    plan = prepare_writeback(project_root, updates)
    return plan.changes, apply_writeback(project_root, plan)
