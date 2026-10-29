from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from kiprod.rfq.approval import has_current_approval, package_sha256

_RFQ_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TRANSITIONS = {
    "draft": {"awaiting_approval"},
    "awaiting_approval": {"sent", "declined", "expired"},
    "sent": {"acknowledged", "quoted", "partial", "declined", "expired", "no_response"},
    "acknowledged": {"quoted", "partial", "declined", "expired", "no_response"},
    "quoted": set(),
    "partial": set(),
    "declined": set(),
    "expired": set(),
    "no_response": set(),
}


class RFQStatus(BaseModel):
    rfq_id: str
    recipient: str
    payload_path: str
    payload_sha256: str
    state: str
    updated_at: str


def _connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfqs (
            rfq_id TEXT PRIMARY KEY,
            recipient TEXT NOT NULL,
            payload_path TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfq_transitions (
            transition_id INTEGER PRIMARY KEY,
            rfq_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            FOREIGN KEY (rfq_id) REFERENCES rfqs(rfq_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfq_delivery_attempts (
            attempt_id INTEGER PRIMARY KEY,
            rfq_id TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            succeeded INTEGER NOT NULL,
            detail TEXT NOT NULL,
            FOREIGN KEY (rfq_id) REFERENCES rfqs(rfq_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfq_inbox_messages (
            message_sha256 TEXT PRIMARY KEY,
            rfq_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            attachment_names TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            FOREIGN KEY (rfq_id) REFERENCES rfqs(rfq_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS rfq_mailbox_cursors (
            provider TEXT PRIMARY KEY,
            cursor TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    connection.commit()
    return connection


def register_email_draft(
    database: Path,
    rfq_id: str,
    recipient: str,
    payload: Path,
) -> RFQStatus:
    """Record the saved email and move the RFQ from draft to awaiting approval."""
    if not _RFQ_ID.fullmatch(rfq_id):
        raise ValueError("RFQ ID must be 2–128 letters, digits, dots, underscores, or hyphens")
    if not payload.is_file():
        raise ValueError(f"RFQ email draft does not exist: {payload}")
    payload_path = payload.resolve()
    digest = package_sha256(payload_path)
    now = datetime.now(UTC).isoformat()
    with _connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute(
                "INSERT INTO rfqs VALUES (?, ?, ?, ?, ?, ?)",
                (rfq_id, recipient, str(payload_path), digest, "draft", now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"RFQ ID already exists: {rfq_id}") from exc
        connection.execute(
            "INSERT INTO rfq_transitions (rfq_id, from_state, to_state, occurred_at) "
            "VALUES (?, ?, ?, ?)",
            (rfq_id, None, "draft", now),
        )
        connection.execute(
            "UPDATE rfqs SET state = ?, updated_at = ? WHERE rfq_id = ?",
            ("awaiting_approval", now, rfq_id),
        )
        connection.execute(
            "INSERT INTO rfq_transitions (rfq_id, from_state, to_state, occurred_at) "
            "VALUES (?, ?, ?, ?)",
            (rfq_id, "draft", "awaiting_approval", now),
        )
    return RFQStatus(
        rfq_id=rfq_id,
        recipient=recipient,
        payload_path=str(payload_path),
        payload_sha256=digest,
        state="awaiting_approval",
        updated_at=now,
    )


def get_rfq_status(database: Path, rfq_id: str) -> RFQStatus | None:
    if not database.is_file():
        return None
    with sqlite3.connect(database, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute("SELECT * FROM rfqs WHERE rfq_id = ?", (rfq_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return None
            raise
    return RFQStatus.model_validate(dict(row)) if row is not None else None


def transition_rfq(database: Path, rfq_id: str, next_state: str) -> RFQStatus:
    """Append an allowed state transition; entering sent requires current approval."""
    with _connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM rfqs WHERE rfq_id = ?", (rfq_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown RFQ ID: {rfq_id}")
        current = str(row["state"])
        if next_state not in _TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid RFQ state transition: {current} -> {next_state}")
        if next_state == "sent":
            payload = Path(str(row["payload_path"]))
            if (
                not payload.is_file()
                or package_sha256(payload) != row["payload_sha256"]
                or not has_current_approval(payload, database)
            ):
                raise ValueError("RFQ cannot enter sent without approval of the exact saved email")
        now = datetime.now(UTC).isoformat()
        connection.execute(
            "UPDATE rfqs SET state = ?, updated_at = ? WHERE rfq_id = ?",
            (next_state, now, rfq_id),
        )
        connection.execute(
            "INSERT INTO rfq_transitions (rfq_id, from_state, to_state, occurred_at) "
            "VALUES (?, ?, ?, ?)",
            (rfq_id, current, next_state, now),
        )
        updated = dict(row)
        updated.update(state=next_state, updated_at=now)
    return RFQStatus.model_validate(updated)


def record_delivery_attempt(
    database: Path, rfq_id: str, *, succeeded: bool, detail: str = ""
) -> None:
    if not database.is_file():
        raise ValueError(f"unknown RFQ database: {database}")
    now = datetime.now(UTC).isoformat()
    with _connect(database) as connection:
        exists = connection.execute("SELECT 1 FROM rfqs WHERE rfq_id = ?", (rfq_id,)).fetchone()
        if exists is None:
            raise ValueError(f"unknown RFQ ID: {rfq_id}")
        connection.execute(
            "INSERT INTO rfq_delivery_attempts "
            "(rfq_id, attempted_at, succeeded, detail) VALUES (?, ?, ?, ?)",
            (rfq_id, now, int(succeeded), detail[:1000]),
        )


def get_mailbox_cursor(database: Path, provider: str) -> str | None:
    if not database.is_file():
        return None
    with sqlite3.connect(database, timeout=10) as connection:
        try:
            row = connection.execute(
                "SELECT cursor FROM rfq_mailbox_cursors WHERE provider = ?", (provider,)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return None
            raise
    return str(row[0]) if row is not None else None


def save_mailbox_cursor(database: Path, provider: str, cursor: str | None) -> None:
    now = datetime.now(UTC).isoformat()
    with _connect(database) as connection:
        if cursor is None:
            connection.execute("DELETE FROM rfq_mailbox_cursors WHERE provider = ?", (provider,))
        else:
            connection.execute(
                "INSERT INTO rfq_mailbox_cursors (provider, cursor, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET cursor = excluded.cursor, "
                "updated_at = excluded.updated_at",
                (provider, cursor, now),
            )
