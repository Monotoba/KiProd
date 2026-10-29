from __future__ import annotations

import getpass
import re
from pathlib import Path

_HIDDEN_LAYER = re.compile(r'\(layer\s+"[^"\r\n]+"[^)]*\bhide\b', re.IGNORECASE)


def scan_privacy(
    root: Path,
    *,
    sensitive_roots: list[Path] | None = None,
    usernames: list[str] | None = None,
) -> list[str]:
    """Find embedded local paths, configured usernames, and explicit hidden-layer markers."""
    roots = sensitive_roots if sensitive_roots is not None else [Path.home()]
    users = usernames if usernames is not None else [getpass.getuser()]
    path_patterns = [
        re.compile(
            rf"(?<![A-Za-z0-9_.-]){re.escape(path.resolve().as_posix().casefold().rstrip('/'))}"
            r"(?![A-Za-z0-9_.-])",
            re.IGNORECASE,
        )
        for path in roots
    ]
    user_patterns = [
        re.compile(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", re.IGNORECASE)
        for name in users
        if name.strip()
    ]
    findings: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"MANIFEST.sha256", "MANIFEST.sha256.sig"}:
            continue
        content = path.read_bytes().decode("utf-8", errors="ignore")
        normalized = content.replace("\\", "/")
        name = path.relative_to(root).as_posix()
        if any(pattern.search(normalized) for pattern in path_patterns):
            findings.append(f"{name}: embedded local filesystem path")
        if any(pattern.search(content) for pattern in user_patterns):
            findings.append(f"{name}: embedded local username")
        if _HIDDEN_LAYER.search(content):
            findings.append(f"{name}: hidden layer declaration")
    return findings
