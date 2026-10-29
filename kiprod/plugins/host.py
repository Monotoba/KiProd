from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
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
    adapter_class: type[object] | None

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


def _load_module(plugin_dir: Path, module_name: str) -> ModuleType:
    relative = Path(*module_name.split("."))
    module_path = (plugin_dir / relative).with_suffix(".py").resolve()
    root = plugin_dir.resolve()
    if not module_path.is_relative_to(root):
        raise PluginError("adapter module path escapes the plugin directory")
    if not module_path.is_file():
        raise PluginError(f"adapter module not found: {module_path}")
    spec = importlib.util.spec_from_file_location(f"kiprod_plugin_{plugin_dir.name}", module_path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot load adapter module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugin(plugin_dir: Path) -> LoadedPlugin:
    manifest = load_manifest(plugin_dir)
    adapter_class: type[object] | None = None
    if manifest.adapter is not None:
        module = _load_module(plugin_dir, manifest.adapter.module)
        candidate = getattr(module, manifest.adapter.class_name, None)
        if not isinstance(candidate, type):
            raise PluginError(
                f"adapter class {manifest.adapter.class_name!r} not found in "
                f"{manifest.adapter.module}"
            )
        adapter_class = candidate
    return LoadedPlugin(path=plugin_dir.resolve(), manifest=manifest, adapter_class=adapter_class)


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
