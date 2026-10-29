"""Small standard-library bridge from KiCad launchers to an installed KiProd GUI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def launcher_config_path() -> Path:
    configured = os.environ.get("KIPROD_LAUNCHER_CONFIG")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "kiprod" / "launcher.json"


def load_launcher_config() -> tuple[Path, Path]:
    config_path = launcher_config_path()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"KiProd launcher is not configured; run scripts/install_kicad_launchers.py "
            f"from the KiProd environment ({config_path})"
        ) from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"invalid KiProd launcher configuration: {config_path}")
    interpreter = config.get("python_executable")
    source_root = config.get("source_root")
    if not isinstance(interpreter, str) or not isinstance(source_root, str):
        raise RuntimeError(f"launcher configuration is missing required paths: {config_path}")
    python_path = Path(interpreter).expanduser()
    root_path = Path(source_root).expanduser()
    if not python_path.is_file():
        raise RuntimeError(f"configured Python interpreter was not found: {python_path}")
    if not (root_path / "kiprod" / "__main__.py").is_file():
        raise RuntimeError(f"configured KiProd source directory was not found: {root_path}")
    return python_path, root_path


def project_root_from_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_file() and candidate.suffix == ".kicad_pro":
        candidate = candidate.parent
    elif candidate.is_file() or candidate.suffix == ".kicad_pcb":
        candidate = candidate.parent
    candidate = candidate.resolve()
    if any(candidate.glob("*.kicad_pro")):
        return candidate
    raise RuntimeError(f"could not find a KiCad project file beside {path}")


def _application_environment(source_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)
    secret_markers = ("PASSWORD", "SECRET", "CREDENTIAL", "ACCESS_KEY", "API_KEY", "TOKEN")
    for name in tuple(environment):
        if name != "KICAD_API_TOKEN" and any(marker in name.upper() for marker in secret_markers):
            environment.pop(name)
    environment["PYTHONPATH"] = str(source_root)
    return environment


def launch_gui(project_path: str | Path, mode: str = "open") -> int:
    if mode not in {"open", "all", "quote-only"}:
        raise ValueError(f"unsupported KiProd launcher mode: {mode}")
    root = project_root_from_path(project_path)
    python_path, source_root = load_launcher_config()
    environment = _application_environment(source_root)
    subprocess.Popen(
        [
            str(python_path),
            "-m",
            "kiprod",
            "gui",
            "--project",
            str(root),
            "--mode",
            mode,
        ],
        cwd=root,
        env=environment,
        close_fds=os.name != "nt",
        start_new_session=os.name != "nt",
    )
    return 0


def run_bom_generator(netlist_path: str | Path, output_path: str | Path) -> int:
    """Run the offline production flow and export its normalized BOM for KiCad."""
    netlist = Path(netlist_path).expanduser().resolve()
    if not netlist.is_file():
        raise RuntimeError(f"KiCad netlist input does not exist: {netlist}")
    project_root = project_root_from_path(netlist.parent)
    destination = Path(output_path).expanduser()
    if destination.suffix.casefold() != ".csv":
        destination = destination.with_suffix(".csv")
    python_path, source_root = load_launcher_config()
    environment = _application_environment(source_root)
    result = subprocess.run(
        [
            str(python_path),
            "-m",
            "kiprod",
            "run",
            "--project",
            str(project_root),
            "--non-interactive",
        ],
        cwd=project_root,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    generated = project_root / "docs" / "production" / "bom" / "bom.csv"
    if not generated.is_file():
        raise RuntimeError(f"KiProd run completed without creating {generated}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generated, destination)
    return 0
