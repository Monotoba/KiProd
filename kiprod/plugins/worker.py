"""Subprocess entry point for executing a plugin adapter method."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_adapter(root: Path, module_name: str, class_name: str) -> Any:
    module_path = (root / Path(*module_name.split("."))).with_suffix(".py").resolve()
    if not module_path.is_relative_to(root.resolve()):
        raise ValueError("adapter module path escapes the plugin directory")
    spec = importlib.util.spec_from_file_location(f"kiprod_worker_{root.name}", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load adapter module {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter_class = getattr(module, class_name)
    return adapter_class()


def main() -> int:
    request = json.loads(sys.stdin.read())
    root = Path(request["plugin_dir"])
    adapter = _load_adapter(root, request["module"], request["class"])
    method = getattr(adapter, request["method"])
    result = method(*request.get("args", []), **request.get("kwargs", {}))
    sys.stdout.write(json.dumps({"ok": True, "result": result}, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1)
