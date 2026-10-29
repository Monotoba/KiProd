from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from kiprod.rfq.privacy import scan_privacy

_MANIFEST = "MANIFEST.sha256"
_SIGNATURE = f"{_MANIFEST}.sig"
_HASH_LINE = re.compile(r"^([0-9a-f]{64}) ([0-9]+)  (.+)$")


def _safe_name(name: str, *, allow_metadata: bool = False) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {"", ".", ".."} for part in path.parts)
        or (not allow_metadata and name in {_MANIFEST, _SIGNATURE})
    ):
        raise ValueError(f"unsafe or reserved RFQ package path: {name!r}")
    return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"command failed ({command[0]}): {exc}") from exc


def build_package(
    files: Mapping[str, Path],
    output: Path,
    signing_key: str,
    *,
    scanner: str = "clamscan",
) -> Path:
    """Scan, manifest, sign, and zip only explicitly selected RFQ files."""
    if not files:
        raise ValueError("an RFQ package requires at least one input file")
    if not signing_key.strip():
        raise ValueError("a GPG signing key is required")
    names = [_safe_name(name) for name in files]
    if len(names) != len(set(names)):
        raise ValueError("RFQ package paths must be unique")
    for path in files.values():
        if not path.is_file():
            raise ValueError(f"RFQ package input is not a file: {path}")
    gpg = shutil.which("gpg")
    scanner_path = shutil.which(scanner)
    if gpg is None:
        raise RuntimeError("gpg is required to sign RFQ packages")
    if scanner_path is None:
        raise RuntimeError(f"configured malware scanner is not installed: {scanner}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="kiprod-rfq-") as temporary:
        stage = Path(temporary)
        entries: list[tuple[str, Path]] = []
        for name, source in zip(names, files.values(), strict=True):
            target = stage.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            entries.append((name, target))
        manifest = "".join(
            f"{_sha256(path)} {path.stat().st_size}  {name}\n" for name, path in sorted(entries)
        )
        manifest_path = stage / _MANIFEST
        manifest_path.write_text(manifest, encoding="utf-8", newline="\n")

        privacy_findings = scan_privacy(stage)
        if privacy_findings:
            raise RuntimeError("RFQ privacy scan blocked package: " + "; ".join(privacy_findings))

        scan = _run([scanner_path, "--no-summary", "-r", str(stage)])
        if scan.returncode != 0:
            reason = "malware detected" if scan.returncode == 1 else "scanner failed"
            raise RuntimeError(f"RFQ package blocked: {reason}: {scan.stdout}{scan.stderr}".strip())

        signature_path = stage / _SIGNATURE
        sign = _run(
            [
                gpg,
                "--batch",
                "--yes",
                "--local-user",
                signing_key,
                "--detach-sign",
                "--output",
                str(signature_path),
                str(manifest_path),
            ]
        )
        if sign.returncode != 0 or not signature_path.is_file():
            raise RuntimeError(f"RFQ manifest signing failed: {sign.stderr.strip()}")

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage).as_posix())
    return output


def verify_package(package: Path) -> list[str]:
    """Verify archive paths, manifest hashes/sizes, and GPG detached signature."""
    gpg = shutil.which("gpg")
    if gpg is None:
        raise RuntimeError("gpg is required to verify RFQ packages")
    with (
        zipfile.ZipFile(package) as archive,
        TemporaryDirectory(prefix="kiprod-rfq-verify-") as tmp,
    ):
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("RFQ package contains duplicate paths")
        for name in names:
            _safe_name(name, allow_metadata=True)
        if _MANIFEST not in names or _SIGNATURE not in names:
            raise ValueError("RFQ package is missing its manifest or signature")
        stage = Path(tmp)
        archive.extractall(stage)
        manifest_path = stage / _MANIFEST
        signature_path = stage / _SIGNATURE
        listed: set[str] = set()
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            match = _HASH_LINE.fullmatch(line)
            if match is None:
                raise ValueError(f"invalid RFQ manifest line: {line!r}")
            digest, size_text, name = match.groups()
            safe_name = _safe_name(name)
            if safe_name in listed:
                raise ValueError(f"duplicate RFQ manifest entry: {safe_name}")
            listed.add(safe_name)
            target = stage.joinpath(*PurePosixPath(safe_name).parts)
            if not target.is_file() or target.stat().st_size != int(size_text):
                raise ValueError(f"RFQ package file missing or size mismatch: {safe_name}")
            if _sha256(target) != digest:
                raise ValueError(f"RFQ package hash mismatch: {safe_name}")
        expected = set(names) - {_MANIFEST, _SIGNATURE}
        if listed != expected:
            raise ValueError("RFQ package contents do not match its manifest")
        result = _run([gpg, "--verify", str(signature_path), str(manifest_path)])
        if result.returncode != 0:
            raise ValueError(f"RFQ signature verification failed: {result.stderr.strip()}")
        return sorted(listed)
