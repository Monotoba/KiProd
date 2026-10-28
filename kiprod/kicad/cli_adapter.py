from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class KiCadCliError(RuntimeError):
    pass


def executable() -> str | None:
    """Return the configured KiCad CLI executable when it is available."""
    return shutil.which("kicad-cli")


def version() -> str | None:
    command = executable()
    if command is None:
        return None
    result = subprocess.run([command, "version"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def export_bom(schematic: Path, output: Path, variant: str | None = None) -> Path:
    """Export an ungrouped CSV BOM using KiCad's supported command-line interface."""
    command = executable()
    if command is None:
        raise KiCadCliError("kicad-cli is not installed or is not on PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        command,
        "sch",
        "export",
        "bom",
        "--output",
        str(output),
        "--fields",
        "Reference,Value,Footprint,MPN,QUANTITY,DNP",
        "--labels",
        "Reference,Value,Footprint,MPN,Quantity,DNP",
        "--exclude-dnp",
        str(schematic),
    ]
    if variant:
        args[6:6] = ["--variant", variant]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise KiCadCliError(f"kicad-cli BOM export failed: {detail}")
    if not output.is_file():
        raise KiCadCliError(f"kicad-cli reported success but did not create {output}")
    return output
