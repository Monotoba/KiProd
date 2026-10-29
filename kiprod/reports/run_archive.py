from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_inputs(inputs: list[Path], bom: Path | None, run_dir: Path) -> dict[str, Any]:
    """Copy calculation inputs into an immutable run folder and write its manifest."""
    run_dir.mkdir(parents=True, exist_ok=True)
    input_dir = run_dir / "inputs"
    input_dir.mkdir(exist_ok=True)
    archived: list[dict[str, str]] = []
    for index, source in enumerate(inputs, start=1):
        destination = input_dir / f"landed-{index:03d}.json"
        shutil.copyfile(source, destination)
        archived.append(
            {"path": str(destination.relative_to(run_dir)), "sha256": _sha256(destination)}
        )
    archived_bom: dict[str, str] | None = None
    if bom is not None:
        destination = input_dir / "bom.normalized.json"
        shutil.copyfile(bom, destination)
        archived_bom = {
            "path": str(destination.relative_to(run_dir)),
            "sha256": _sha256(destination),
        }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "landed_cost_inputs": archived,
        "bom": archived_bom,
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported report run manifest version")
    for entry in [
        *manifest.get("landed_cost_inputs", []),
        *([manifest["bom"]] if manifest.get("bom") else []),
    ]:
        path = (run_dir / entry["path"]).resolve()
        if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
            raise ValueError(f"invalid archived input path: {entry['path']}")
        if _sha256(path) != entry["sha256"]:
            raise ValueError(f"archived input hash mismatch: {entry['path']}")
    result: dict[str, Any] = manifest
    return result


def input_paths(run_dir: Path, manifest: dict[str, Any]) -> tuple[list[Path], Path | None]:
    inputs = [run_dir / item["path"] for item in manifest.get("landed_cost_inputs", [])]
    bom_entry = manifest.get("bom")
    return inputs, run_dir / bom_entry["path"] if bom_entry else None
