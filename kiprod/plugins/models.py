from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Region(BaseModel):
    country: str | None = None
    ships_from: list[str] = Field(default_factory=list)
    currency: str | None = None


class AdapterSpec(BaseModel):
    module: str = "adapter"
    class_name: str = Field(alias="class")
    min_core: str | None = None


class Credentials(BaseModel):
    key: str
    label: str
    secret: bool = True


class Permissions(BaseModel):
    network: list[str] = Field(default_factory=list)
    email: bool = False
    browser: bool = False
    filesystem_write_outside_run: bool = False


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    version: str
    homepage: str | None = None
    integration_status: Literal["profile_only", "adapter_configured"] | None = None
    resource_types: list[str] = Field(default_factory=list, alias="resources")
    region: Region = Field(default_factory=Region)
    adapter: AdapterSpec | None = None
    credentials: list[Credentials] = Field(default_factory=list)
    permissions: Permissions = Field(default_factory=Permissions)
    capabilities: dict[str, object] = Field(default_factory=dict)
    fields: list[dict[str, object]] = Field(default_factory=list)

    @property
    def status_label(self) -> str:
        if self.integration_status == "profile_only":
            return "Profile only"
        if self.integration_status == "adapter_configured":
            return "Adapter available"
        return "Adapter configured" if self.adapter is not None else "Profile only"

    @field_validator("fields")
    @classmethod
    def valid_fields(cls, fields: list[dict[str, object]]) -> list[dict[str, object]]:
        keys: set[str] = set()
        supported = {
            "string",
            "text",
            "int",
            "float",
            "bool",
            "enum",
            "multi_enum",
            "date",
            "file",
            "secret",
            "table",
            "group",
        }
        for item in fields:
            key = item.get("key")
            field_type = item.get("type", "string")
            if not isinstance(key, str) or not key.strip():
                raise ValueError("each plugin field requires a non-empty key")
            if key in keys:
                raise ValueError(f"duplicate plugin field key: {key}")
            if field_type not in supported:
                raise ValueError(f"unsupported plugin field type for {key}: {field_type}")
            keys.add(key)
        return fields

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value):
            raise ValueError("plugin id must be non-empty and contain no whitespace")
        return value
