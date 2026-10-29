"""Subprocess entry point for executing a plugin adapter method."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


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
    return adapter_class(_WorkerHttpClient())


class _WorkerHttpClient:
    """Line-based HTTP RPC; the trusted parent performs all network access."""

    @staticmethod
    def request(
        method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None
    ) -> dict[str, Any]:
        message = {
            "type": "http",
            "method": method,
            "url": url,
            "headers": headers or {},
            "body": body.decode("latin1") if body is not None else None,
        }
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()
        response = json.loads(sys.stdin.readline())
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "HTTP request rejected"))
        result: dict[str, Any] = response["response"]
        return result

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
        return _WorkerResponse(self.request("GET", url, headers=headers))

    def post(self, url: str, body: bytes, *, headers: dict[str, str] | None = None) -> Any:
        return _WorkerResponse(self.request("POST", url, headers=headers, body=body))


class _WorkerResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self.status = data["status"]
        self.headers = data["headers"]
        self._body = data["body"]

    def json(self) -> Any:
        return json.loads(self._body)


def main() -> int:
    request = json.loads(sys.stdin.readline())
    root = Path(request["plugin_dir"])
    adapter = _load_adapter(root, request["module"], request["class"])
    method = getattr(adapter, request["method"])
    result = method(*request.get("args", []), **request.get("kwargs", {}))
    sys.stdout.write(
        json.dumps({"type": "result", "ok": True, "result": result}, default=_json_default)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stdout.write(
            json.dumps({"type": "result", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            + "\n"
        )
        raise SystemExit(1)
