from __future__ import annotations

import getpass
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

_HIDDEN_LAYER = re.compile(r'\(layer\s+"[^"\r\n]+"[^)]*\bhide\b', re.IGNORECASE)
_HIDDEN_DOCUMENT_CONTENT = re.compile(
    r"(?:\bstate\s*=\s*['\"](?:hidden|veryhidden)['\"]|"
    r"\bdisplay\s*=\s*['\"]false['\"]|\bhidden\s*=\s*['\"](?:1|true)['\"])",
    re.IGNORECASE,
)
_OFFICE_SUFFIXES = {".docx", ".xlsx", ".xlsm", ".pptx", ".odt", ".ods", ".odp"}


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
        raw = path.read_bytes()
        contents = _structured_contents(path, raw, findings, root)
        name = path.relative_to(root).as_posix()
        all_text = "\n".join(contents)
        normalized = all_text.replace("\\", "/")
        if any(pattern.search(normalized) for pattern in path_patterns):
            findings.append(f"{name}: embedded local filesystem path")
        if any(pattern.search(all_text) for pattern in user_patterns):
            findings.append(f"{name}: embedded local username")
        if any(_HIDDEN_LAYER.search(text) for text in contents):
            findings.append(f"{name}: hidden layer declaration")
        if any(_HIDDEN_DOCUMENT_CONTENT.search(text) for text in contents):
            findings.append(f"{name}: hidden Office document content")
        if path.suffix.casefold() == ".pdf" and b"/OCProperties" in raw:
            if re.search(rb"/OFF\s*\[", raw):
                findings.append(f"{name}: hidden PDF optional-content layer")
    return findings


def _structured_contents(
    path: Path,
    raw: bytes,
    findings: list[str],
    root: Path,
) -> list[str]:
    name = path.relative_to(root).as_posix()
    if path.suffix.casefold() == ".pdf":
        executable = shutil.which("pdfinfo")
        if executable is None:
            findings.append(f"{name}: PDF metadata inspection requires local pdfinfo")
            return [raw.decode("latin-1", errors="ignore")]
        try:
            result = subprocess.run(
                [executable, str(path)],
                capture_output=True,
                check=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            findings.append(f"{name}: PDF metadata inspection failed")
            return [raw.decode("latin-1", errors="ignore")]
        return [raw.decode("latin-1", errors="ignore"), result.stdout]
    if path.suffix.casefold() in _OFFICE_SUFFIXES:
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    findings.append(f"{name}: Office archive exceeds privacy scan size limit")
                    return [raw.decode("utf-8", errors="ignore")]
                contents = list(archive.namelist())
                for item in archive.namelist():
                    if item.casefold().endswith((".xml", ".rels", ".txt")):
                        contents.append(archive.read(item).decode("utf-8", errors="ignore"))
                    elif item.casefold().endswith("vbaproject.bin"):
                        contents.append(archive.read(item).decode("latin-1", errors="ignore"))
                return contents
        except (OSError, zipfile.BadZipFile, RuntimeError):
            findings.append(f"{name}: Office archive could not be inspected")
            return [raw.decode("utf-8", errors="ignore")]
    content = raw.decode("utf-8", errors="ignore")
    if path.suffix.casefold() == ".kicad_prl":
        try:
            data = json.loads(content)
            board = data.get("board", {}) if isinstance(data, dict) else {}
            visibility = board.get("visible_layers") if isinstance(board, dict) else None
            if isinstance(visibility, str):
                masks = visibility.split("_")
                if any(mask and set(mask.casefold()) != {"f"} for mask in masks):
                    findings.append(f"{name}: hidden KiCad layer visibility state")
        except json.JSONDecodeError:
            findings.append(f"{name}: KiCad layer visibility state could not be inspected")
    return [content]
