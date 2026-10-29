from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PromptRole = Literal["reasoning", "extraction", "writer", "local_only"]
_TASK = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FIELDS = {"role", "schema", "version"}
_MAX_PROMPT_BYTES = 64 * 1024


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    task: str
    role: PromptRole
    schema: str
    version: str
    body: str
    path: Path


def load_prompt(
    task: str,
    *,
    search_dirs: list[Path] | None = None,
) -> PromptTemplate:
    """Load the first matching prompt; earlier search directories take precedence."""
    if not _TASK.fullmatch(task):
        raise PromptError(f"invalid prompt task name: {task}")
    roots = [*(search_dirs or []), Path(__file__).resolve().parents[1] / "prompts"]
    for root in roots:
        candidate = (root / f"{task}.md").resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise PromptError("prompt path escapes its search directory")
        if candidate.is_file():
            return _parse_prompt(task, candidate)
    raise PromptError(f"prompt not found: {task}")


def _parse_prompt(task: str, path: Path) -> PromptTemplate:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PromptError(f"cannot read prompt {path}: {exc}") from exc
    if len(raw) > _MAX_PROMPT_BYTES:
        raise PromptError(f"prompt exceeds {_MAX_PROMPT_BYTES} byte limit: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError(f"prompt is not UTF-8: {path}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptError(f"prompt must start with YAML front matter: {path}")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise PromptError(f"prompt front matter is not closed: {path}") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        normalized_key = key.strip()
        if not separator or normalized_key not in _FIELDS:
            raise PromptError(f"unsupported prompt front matter line: {line}")
        if normalized_key in metadata:
            raise PromptError(f"duplicate prompt front matter field: {normalized_key}")
        metadata[normalized_key] = value.strip().strip("\"'")
    missing = sorted(_FIELDS - metadata.keys())
    if missing:
        raise PromptError("prompt front matter is missing: " + ", ".join(missing))
    role = metadata["role"]
    if role not in {"reasoning", "extraction", "writer", "local_only"}:
        raise PromptError(f"unsupported prompt role: {role}")
    schema = metadata["schema"]
    version = metadata["version"]
    if not schema or not version:
        raise PromptError("prompt schema and version must be non-empty")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise PromptError(f"prompt body is empty: {path}")
    return PromptTemplate(
        task=task,
        role=role,  # type: ignore[arg-type]
        schema=schema,
        version=version,
        body=body,
        path=path,
    )
