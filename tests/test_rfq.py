from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

import kiprod.rfq.package as rfq_package


def _mock_tools(monkeypatch: pytest.MonkeyPatch, *, scan_status: int = 0) -> None:
    monkeypatch.setattr(
        rfq_package.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"gpg", "clamscan"} else None,
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--local-user" in command:
            signature = Path(command[command.index("--output") + 1])
            signature.write_bytes(b"mock detached signature")
            return subprocess.CompletedProcess(command, 0, "", "")
        status = scan_status if "--no-summary" in command else 0
        return subprocess.CompletedProcess(command, status, "", "")

    monkeypatch.setattr(rfq_package.subprocess, "run", run)


def test_package_contains_explicit_files_manifest_and_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\nR1,1\n", encoding="utf-8")
    output = tmp_path / "out" / "package.zip"

    result = rfq_package.build_package({"bom.csv": source}, output, "test-key")

    assert result == output
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"bom.csv", "MANIFEST.sha256", "MANIFEST.sha256.sig"}
        manifest = archive.read("MANIFEST.sha256").decode()
        assert "13  bom.csv" in manifest
    assert rfq_package.verify_package(output) == ["bom.csv"]


def test_tampered_package_file_fails_manifest_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "drawing.pdf"
    source.write_bytes(b"original")
    output = tmp_path / "package.zip"
    rfq_package.build_package({"drawing.pdf": source}, output, "test-key")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(tampered, "w") as changed:
        for name in original.namelist():
            payload = b"changed" if name == "drawing.pdf" else original.read(name)
            changed.writestr(name, payload)

    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        rfq_package.verify_package(tampered)


def test_scanner_failure_blocks_package_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch, scan_status=1)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="malware detected"):
        rfq_package.build_package({"bom.csv": source}, tmp_path / "package.zip", "test-key")
    assert not (tmp_path / "package.zip").exists()


@pytest.mark.parametrize("name", ["../secret.txt", "/etc/passwd", "folder\\file.txt"])
def test_package_rejects_unsafe_archive_paths(name: str, tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        rfq_package.build_package({name: source}, tmp_path / "package.zip", "test-key")
