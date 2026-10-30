#!/usr/bin/env python3
"""Install KiProd's lightweight IPC and legacy launchers for a KiCad version."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "launchers" / "shared"))

from kiprod_launcher import launcher_config_path  # noqa: E402


def documents_home() -> Path:
    configured = os.environ.get("KICAD_DOCUMENTS_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt" or sys.platform == "darwin":
        return Path.home() / "Documents" / "KiCad"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "kicad"


def swig_plugin_directory() -> Path:
    """Return KiCad's legacy PCB Action Plugin search directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "kicad" / "scripting" / "plugins"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "kicad"
            / "scripting"
            / "plugins"
        )
    return Path.home() / ".kicad" / "scripting" / "plugins"


def _remove_installed_files(directory: Path, filenames: tuple[str, ...]) -> None:
    """Remove only launcher files previously installed by KiProd."""
    for filename in filenames:
        (directory / filename).unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


def _copy_bundle(source: Path, destination: Path, filenames: tuple[str, ...]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        shutil.copy2(source / filename, destination / filename)


def _write_launcher_config(path: Path, python_path: Path, source_root: Path) -> None:
    current: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid launcher configuration JSON: {path}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"launcher configuration must contain a JSON object: {path}")
        current = loaded
    current.update(
        python_executable=str(python_path),
        source_root=str(source_root),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            json.dump(current, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _check_runtime(python_path: Path, source_root: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(source_root), environment.get("PYTHONPATH", "")) if item
    )
    result = subprocess.run(
        [str(python_path), "-c", "import kiprod; import PySide6"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            "the configured Python must import KiProd and PySide6; run "
            f"scripts/setup-gui.sh in this environment first ({detail})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-version", default="10.0", help="KiCad major.minor version")
    parser.add_argument(
        "--documents-home",
        type=Path,
        help="KiCad documents home (defaults to KICAD_DOCUMENTS_HOME or the platform path)",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter with KiProd and the GUI extra installed",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=PROJECT_ROOT,
        help="KiProd source checkout or package root",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+", args.kicad_version):
        parser.error("--kicad-version must have the form major.minor, for example 10.0")
    major = int(args.kicad_version.split(".", maxsplit=1)[0])
    if major < 8:
        parser.error("KiProd launchers support KiCad 8.0 and newer")
    # Preserve the venv executable path; resolving a symlink can escape its venv.
    python_path = args.python.expanduser().absolute()
    source_root = args.source_root.expanduser().resolve()
    if not python_path.is_file():
        parser.error(f"Python interpreter does not exist: {python_path}")
    if not (source_root / "kiprod" / "__main__.py").is_file():
        parser.error(f"KiProd package not found under source root: {source_root}")

    try:
        _check_runtime(python_path, source_root)
        config_path = launcher_config_path()
        _write_launcher_config(config_path, python_path, source_root)
        root = (args.documents_home or documents_home()).expanduser() / args.kicad_version
        shared = PROJECT_ROOT / "launchers" / "shared"

        bomgen_dir = root / "scripting" / "kiprod_bomgen"
        _copy_bundle(
            PROJECT_ROOT / "launchers" / "bomgen",
            bomgen_dir,
            ("bomgen.py",),
        )
        shutil.copy2(shared / "kiprod_launcher.py", bomgen_dir / "kiprod_launcher.py")

        if 9 <= major <= 10:
            # KiCad's Plugin and Content Manager discovers add-ons here. Keeping
            # both manifests in the same package makes IPC and SWIG actions
            # available from the location KiCad 10 actually scans.
            plugin_dir = root / "3rdparty" / "plugins" / "com_github_monotoba_kiprod"
            _copy_bundle(
                PROJECT_ROOT / "launchers" / "ipc",
                plugin_dir,
                ("plugin.json", "launch.py", "requirements.txt"),
            )
            _copy_bundle(PROJECT_ROOT / "launchers" / "swig", plugin_dir, ("__init__.py",))
            shutil.copy2(shared / "kiprod_launcher.py", plugin_dir / "kiprod_launcher.py")
            shutil.copytree(
                PROJECT_ROOT / "launchers" / "ipc" / "icons",
                plugin_dir / "icons",
                dirs_exist_ok=True,
            )

            # Migrate files written by earlier KiProd installers to avoid
            # duplicate actions from parallel plugin directories.
            _remove_installed_files(
                root / "plugins" / "kiprod",
                ("plugin.json", "launch.py", "requirements.txt", "kiprod_launcher.py"),
            )
            _remove_installed_files(
                swig_plugin_directory() / "kiprod",
                ("__init__.py", "kiprod_launcher.py"),
            )
        elif major == 11:
            ipc_dir = root / "plugins" / "kiprod"
            _copy_bundle(
                PROJECT_ROOT / "launchers" / "ipc",
                ipc_dir,
                ("plugin.json", "launch.py", "requirements.txt"),
            )
            shutil.copy2(shared / "kiprod_launcher.py", ipc_dir / "kiprod_launcher.py")
        elif major == 8:
            swig_dir = swig_plugin_directory() / "kiprod"
            _copy_bundle(PROJECT_ROOT / "launchers" / "swig", swig_dir, ("__init__.py",))
            shutil.copy2(shared / "kiprod_launcher.py", swig_dir / "kiprod_launcher.py")
            shutil.copytree(
                PROJECT_ROOT / "launchers" / "ipc" / "icons",
                swig_dir / "icons",
                dirs_exist_ok=True,
            )
    except (OSError, RuntimeError) as exc:
        print(f"KiCad launcher installation failed: {exc}", file=sys.stderr)
        return 1

    print(f"KiProd launcher configuration: {config_path}")
    print(f"Installed for KiCad {args.kicad_version} under {root}")
    print("Restart KiCad to load the PCB Editor launchers.")
    if 9 <= major <= 10:
        print("For Plugin Manager registration, install the generated KiCad add-on ZIP from file.")
    if major >= 9:
        print("In KiCad, enable the IPC API under Preferences > Plugins.")
    print("Add this command in Schematic Editor > Tools > Generate BOM:")
    bomgen_script = bomgen_dir / "bomgen.py"
    print(f'"{python_path}" "{bomgen_script}" "%I" "%O.csv"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
