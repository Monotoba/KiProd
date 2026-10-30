from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_LAUNCHER = PROJECT_ROOT / "launchers" / "shared" / "kiprod_launcher.py"
INSTALLER = PROJECT_ROOT / "scripts" / "install_kicad_launchers.py"
IPC_MANIFEST = PROJECT_ROOT / "launchers" / "ipc" / "plugin.json"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_module() -> ModuleType:
    return _load_module("kiprod_shared_launcher_test", SHARED_LAUNCHER)


def _configure_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "config" / "launcher.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "python_executable": sys.executable,
                "source_root": str(PROJECT_ROOT),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KIPROD_LAUNCHER_CONFIG", str(config_path))
    return config_path


@pytest.mark.parametrize("mode", ["open", "all", "quote-only"])
def test_launch_gui_uses_project_context_and_scrubs_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launcher_module: ModuleType,
    mode: str,
) -> None:
    _configure_launcher(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "fixture.kicad_pro").write_text("{}", encoding="utf-8")
    board = project / "fixture.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")
    monkeypatch.setenv("KICAD_API_TOKEN", "preserve-for-ipc")
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def capture_popen(args: list[str], **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(launcher_module.subprocess, "Popen", capture_popen)

    assert launcher_module.launch_gui(board, mode) == 0

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-5:] == ["gui", "--project", str(project.resolve()), "--mode", mode]
    environment = kwargs["env"]
    assert "OPENAI_API_KEY" not in environment
    assert environment["KICAD_API_TOKEN"] == "preserve-for-ipc"
    assert environment["PYTHONPATH"] == str(PROJECT_ROOT)
    assert kwargs["cwd"] == project.resolve()


def test_project_root_requires_a_kicad_project_file(
    tmp_path: Path, launcher_module: ModuleType
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    board = project / "fixture.kicad_pcb"
    board.touch()

    with pytest.raises(RuntimeError, match="could not find a KiCad project"):
        launcher_module.project_root_from_path(board)

    (project / "fixture.kicad_pro").touch()
    assert launcher_module.project_root_from_path(board) == project.resolve()


def test_ipc_manifest_uses_reverse_dns_identifier_and_unique_actions() -> None:
    manifest = json.loads(IPC_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["identifier"] == "com.github.monotoba.kiprod"
    identifiers = [action["identifier"] for action in manifest["actions"]]
    assert len(identifiers) == len(set(identifiers))
    assert {action["args"][0] for action in manifest["actions"]} == {
        "all",
        "quote-only",
        "open",
    }


def test_bom_generator_runs_offline_flow_and_copies_bom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher_module: ModuleType
) -> None:
    _configure_launcher(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "fixture.kicad_pro").touch()
    netlist = project / "fixture.xml"
    netlist.write_text("<export />", encoding="utf-8")
    generated = project / "docs" / "production" / "bom" / "bom.csv"
    output = tmp_path / "requested.csv"
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def capture_run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((args, kwargs))
        generated.parent.mkdir(parents=True)
        generated.write_text("References,MPN\nR1,MPN-1\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher_module.subprocess, "run", capture_run)

    assert launcher_module.run_bom_generator(netlist, output) == 0

    assert calls[0][0][-3:] == ["--project", str(project.resolve()), "--non-interactive"]
    assert calls[0][1]["cwd"] == project.resolve()
    assert output.read_text(encoding="utf-8") == "References,MPN\nR1,MPN-1\n"


@pytest.mark.parametrize(
    ("version", "ipc", "swig"),
    [
        ("8.0", False, True),
        ("9.0", True, True),
        ("10.0", True, True),
        ("11.0", True, False),
    ],
)
def test_installer_copies_only_launchers_supported_by_kicad_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    ipc: bool,
    swig: bool,
) -> None:
    monkeypatch.syspath_prepend(str(SHARED_LAUNCHER.parent))
    installer = _load_module("kiprod_installer_test", INSTALLER)
    monkeypatch.setattr(installer, "_check_runtime", lambda _python, _root: None)
    swig_root = tmp_path / "swig_plugins"
    monkeypatch.setattr(installer, "swig_plugin_directory", lambda: swig_root)
    config_path = tmp_path / "config" / "launcher.json"
    monkeypatch.setenv("KIPROD_LAUNCHER_CONFIG", str(config_path))
    documents_home = tmp_path / "KiCad"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INSTALLER),
            "--kicad-version",
            version,
            "--documents-home",
            str(documents_home),
            "--python",
            sys.executable,
            "--source-root",
            str(PROJECT_ROOT),
        ],
    )

    assert installer.main() == 0

    version_root = documents_home / version
    assert (version_root / "scripting" / "kiprod_bomgen" / "bomgen.py").is_file()
    assert (version_root / "plugins" / "kiprod").is_dir() is ipc
    swig_dir = installer.swig_plugin_directory() / "kiprod"
    assert swig_dir.is_dir() is swig
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved_config["python_executable"] == str(Path(sys.executable).absolute())
    assert saved_config["source_root"] == str(PROJECT_ROOT)


def test_installer_uses_kicads_runtime_linux_plugin_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "darwin" or sys.platform == "win32":
        pytest.skip("KiCad uses the platform documents directory on this OS")
    monkeypatch.syspath_prepend(str(SHARED_LAUNCHER.parent))
    installer = _load_module("kiprod_installer_default_path_test", INSTALLER)
    monkeypatch.delenv("KICAD_DOCUMENTS_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))

    assert installer.documents_home() == tmp_path / "share" / "kicad"
    assert installer.swig_plugin_directory() == Path.home() / ".kicad" / "scripting" / "plugins"
