#!/usr/bin/env python3
"""Build the KiCad Plugin and Content Manager ZIP for KiProd."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist" / "kiprod-kicad-addon.zip",
        help="output archive path",
    )
    args = parser.parse_args()

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    with (PROJECT_ROOT / "launchers" / "pcm" / "metadata.json").open(
        encoding="utf-8"
    ) as metadata_file:
        metadata = json.load(metadata_file)
    metadata["versions"][0]["version"] = project["project"]["version"]

    launcher_files = {
        "__init__.py": PROJECT_ROOT / "launchers" / "swig" / "__init__.py",
        "kiprod_launcher.py": PROJECT_ROOT / "launchers" / "shared" / "kiprod_launcher.py",
        "launch.py": PROJECT_ROOT / "launchers" / "ipc" / "launch.py",
        "plugin.json": PROJECT_ROOT / "launchers" / "ipc" / "plugin.json",
        "requirements.txt": PROJECT_ROOT / "launchers" / "ipc" / "requirements.txt",
    }
    output = args.output.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, indent=2) + "\n")
        for archive_name, source in launcher_files.items():
            archive.write(source, f"plugins/{archive_name}")

    print(f"Created KiCad add-on package: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
