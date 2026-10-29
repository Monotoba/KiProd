from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ApprovalRecord(BaseModel):
    approval_id: int
    package_sha256: str
    package_name: str
    user: str
    approved_at: str


def package_sha256(package: Path) -> str:
    """Hash the exact bytes that will be attached or transferred."""
    digest = hashlib.sha256()
    with package.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfq_approvals (
            approval_id INTEGER PRIMARY KEY,
            package_sha256 TEXT NOT NULL,
            package_name TEXT NOT NULL,
            user TEXT NOT NULL,
            approved_at TEXT NOT NULL
        )"""
    )
    connection.commit()
    return connection


def approve_package(
    package: Path,
    database: Path,
    user: str,
    *,
    expected_hash: str | None = None,
) -> ApprovalRecord:
    """Append a human approval bound to the package's exact SHA-256 hash."""
    if not user.strip():
        raise ValueError("approval user must be non-empty")
    if not package.is_file():
        raise ValueError(f"RFQ package does not exist: {package}")
    digest = package_sha256(package)
    if expected_hash is not None and digest != expected_hash:
        raise ValueError("RFQ package changed while approval was being recorded")
    approved_at = datetime.now(UTC).isoformat()
    with _connect(database) as connection:
        cursor = connection.execute(
            "INSERT INTO rfq_approvals "
            "(package_sha256, package_name, user, approved_at) VALUES (?, ?, ?, ?)",
            (digest, package.name, user.strip(), approved_at),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return the approval record ID")
        approval_id = cursor.lastrowid
    return ApprovalRecord(
        approval_id=approval_id,
        package_sha256=digest,
        package_name=package.name,
        user=user.strip(),
        approved_at=approved_at,
    )


def has_current_approval(package: Path, database: Path) -> bool:
    """Return true only when an approval matches the package's current bytes."""
    if not package.is_file() or not database.is_file():
        return False
    digest = package_sha256(package)
    with sqlite3.connect(database, timeout=10) as connection:
        try:
            exists = connection.execute(
                "SELECT 1 FROM rfq_approvals WHERE package_sha256 = ? LIMIT 1", (digest,)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return False
            raise
    return exists is not None
