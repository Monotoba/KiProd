from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kiprod.net.http import HttpClient, HttpError
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

    def call(
        self,
        method: str,
        *args: Any,
        timeout: float = 10.0,
        http: HttpClient | None = None,
        **kwargs: Any,
    ) -> Any:
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
            process = subprocess.Popen(
                [sys.executable, "-m", "kiprod.plugins.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.path,
                env={"PATH": "", "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            )
            timed_out = threading.Event()

            def stop_worker() -> None:
                timed_out.set()
                process.kill()

            timer = threading.Timer(timeout, stop_worker)
            timer.start()
            try:
                return self._broker_worker(process, request, method, http, timed_out)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                    process.wait()
        except OSError as exc:
            raise PluginError(f"failed to start plugin worker: {exc}") from exc

    def _broker_worker(
        self,
        process: subprocess.Popen[str],
        request: dict[str, Any],
        method: str,
        http: HttpClient | None,
        timed_out: threading.Event,
    ) -> Any:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            if not line:
                if timed_out.is_set():
                    raise PluginError(f"plugin {self.manifest.id} timed out calling {method}")
                stderr = process.stderr.read() if process.stderr else ""
                raise PluginError(stderr.strip() or "plugin worker exited without a result")
            payload = json.loads(line)
            if payload.get("type") == "http":
                broker = http or self.http_client()
                try:
                    response = broker.request(
                        payload["method"],
                        payload["url"],
                        headers=payload.get("headers"),
                        body=payload["body"].encode("latin1") if payload.get("body") else None,
                    )
                    reply = {
                        "ok": True,
                        "response": {
                            "status": response.status,
                            "headers": response.headers,
                            "body": response.body.decode("latin1"),
                        },
                    }
                except (HttpError, KeyError, ValueError) as exc:
                    reply = {"ok": False, "error": str(exc)}
                assert process.stdin is not None
                process.stdin.write(json.dumps(reply) + "\n")
                process.stdin.flush()
                continue
            process.stdin.close()
            process.wait()
            if process.returncode != 0 or not payload.get("ok"):
                raise PluginError(payload.get("error", "plugin call failed"))
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
