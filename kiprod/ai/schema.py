from __future__ import annotations

import copy
from typing import Any


def openai_strict_schema(schema: dict[str, object]) -> dict[str, object]:
    """Normalize object schemas for strict Structured Outputs requests."""
    result = copy.deepcopy(schema)

    def normalize(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                normalize(item)
            return
        if not isinstance(node, dict):
            return
        properties = node.get("properties")
        if node.get("type") == "object" and isinstance(properties, dict):
            required = set(node.get("required", []))
            for key, child in properties.items():
                if key not in required:
                    if isinstance(child, dict):
                        _allow_null(child)
                    required.add(key)
                normalize(child)
            node["required"] = sorted(required)
            node["additionalProperties"] = False
        for key in ("items", "anyOf", "oneOf", "allOf", "$defs", "definitions"):
            if key in node:
                normalize(node[key])

    normalize(result)
    return result


def _allow_null(schema: dict[str, Any]) -> None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        schema["type"] = [schema_type, "null"]
    elif isinstance(schema_type, list) and "null" not in schema_type:
        schema["type"] = [*schema_type, "null"]
    elif "anyOf" in schema and isinstance(schema["anyOf"], list):
        if not any(
            isinstance(item, dict) and item.get("type") == "null" for item in schema["anyOf"]
        ):
            schema["anyOf"].append({"type": "null"})
