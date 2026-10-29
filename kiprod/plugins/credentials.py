from __future__ import annotations

from importlib import import_module
from typing import Any


class CredentialStoreUnavailable(RuntimeError):
    pass


def _keyring() -> Any:
    try:
        keyring = import_module("keyring")
    except ImportError as exc:
        raise CredentialStoreUnavailable(
            "credential management requires the GUI extra; run ./scripts/setup-gui.sh"
        ) from exc
    backend_name = type(keyring.get_keyring()).__name__.casefold()
    if "fail" in backend_name or "null" in backend_name:
        raise CredentialStoreUnavailable("no usable operating system keyring is available")
    return keyring


def credential_service(plugin_id: str) -> str:
    return f"kiprod.plugin.{plugin_id}"


def has_credential(plugin_id: str, key: str) -> bool:
    keyring = _keyring()
    try:
        return keyring.get_password(credential_service(plugin_id), key) is not None
    except Exception as exc:
        raise CredentialStoreUnavailable("the operating system keyring could not be read") from exc


def get_credential(plugin_id: str, key: str) -> str | None:
    keyring = _keyring()
    try:
        return keyring.get_password(credential_service(plugin_id), key)
    except Exception as exc:
        raise CredentialStoreUnavailable("the operating system keyring could not be read") from exc


def save_credential(plugin_id: str, key: str, value: str) -> None:
    if not value:
        raise ValueError("credential value must not be empty")
    keyring = _keyring()
    try:
        keyring.set_password(credential_service(plugin_id), key, value)
    except Exception as exc:
        raise CredentialStoreUnavailable(
            "the operating system keyring could not save this value"
        ) from exc
