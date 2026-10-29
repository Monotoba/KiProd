from __future__ import annotations

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
    resource_types: list[str] = Field(default_factory=list, alias="resources")
    region: Region = Field(default_factory=Region)
    adapter: AdapterSpec | None = None
    credentials: list[Credentials] = Field(default_factory=list)
    permissions: Permissions = Field(default_factory=Permissions)
    capabilities: dict[str, object] = Field(default_factory=dict)
    fields: list[dict[str, object]] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value):
            raise ValueError("plugin id must be non-empty and contain no whitespace")
        return value
