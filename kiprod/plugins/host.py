from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kiprod.net.http import HttpClient
from kiprod.plugins.models import Manifest


class PluginError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedPlugin:
    path: Path
    manifest: Manifest

    def http_client(self, **options: Any) -> HttpClient:
        """Create the only supported HTTP client for this plugin's declared hosts."""
        return HttpClient(set(self.manifest.permissions.network), **options)

    def call(self, method: str, *args: Any, timeout: float = 10.0, **kwargs: Any) -> Any:
        """Execute an adapter method in a fresh worker process."""
        if self.manifest.adapter is None:
            raise PluginError(f"plugin {self.manifest.id} has no adapter")
        request = {
            "plugin_dir": str(self.path),
            "module": self.manifest.adapter.module,
            "class": self.manifest.adapter.class_name,
            "method": method,
            "args": args,
            "kwargs": kwargs,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "kiprod.plugins.worker"],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                cwd=self.path,
                env={"PATH": "", "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            )
        except subprocess.TimeoutExpired as exc:
            raise PluginError(f"plugin {self.manifest.id} timed out calling {method}") from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PluginError(f"plugin {self.manifest.id} returned invalid worker output") from exc
        if result.returncode != 0 or not payload.get("ok"):
            raise PluginError(payload.get("error", result.stderr.strip() or "plugin call failed"))
        return payload.get("result")


def load_manifest(plugin_dir: Path) -> Manifest:
    manifest_path = plugin_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        return Manifest.model_validate(raw)
    except OSError as exc:
        raise PluginError(f"cannot read plugin manifest {manifest_path}: {exc}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PluginError(f"invalid plugin manifest {manifest_path}: {exc}") from exc


def _adapter_file(plugin_dir: Path, module_name: str) -> Path:
    relative = Path(*module_name.split("."))
    module_path = (plugin_dir / relative).with_suffix(".py").resolve()
    root = plugin_dir.resolve()
    if not module_path.is_relative_to(root):
        raise PluginError("adapter module path escapes the plugin directory")
    if not module_path.is_file():
        raise PluginError(f"adapter module not found: {module_path}")
    return module_path


def load_plugin(plugin_dir: Path) -> LoadedPlugin:
    manifest = load_manifest(plugin_dir)
    if manifest.adapter is not None:
        _adapter_file(plugin_dir, manifest.adapter.module)
    # Adapter code is deliberately not imported during discovery. It runs only
    # inside the worker when an explicit method call is made.
    return LoadedPlugin(path=plugin_dir.resolve(), manifest=manifest)


def discover_plugins(search_paths: list[Path]) -> list[LoadedPlugin]:
    """Find plugin directories in precedence order; first plugin id wins."""
    found: dict[str, LoadedPlugin] = {}
    for search_path in search_paths:
        if not search_path.is_dir():
            continue
        for manifest_path in sorted(search_path.glob("*/manifest.json")):
            plugin = load_plugin(manifest_path.parent)
            found.setdefault(plugin.manifest.id, plugin)
    return list(found.values())


def check_network_permission(plugin: LoadedPlugin, host: str) -> None:
    if host not in plugin.manifest.permissions.network:
        raise PluginError(f"plugin {plugin.manifest.id} did not declare network access to {host}")
