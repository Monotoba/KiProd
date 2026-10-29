from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel

from kiprod.rfq.workflow import _connect, get_rfq_status, transition_rfq

_SAFE_FILENAME = re.compile(r"[^\w.(), -]+", re.UNICODE)
_MAX_MESSAGE_BYTES = 50 * 1024 * 1024


class InboxImport(BaseModel):
    rfq_id: str
    message_sha256: str
    stored_message: str
    attachments: list[str]
    state: str
    imported_at: str


def _known_rfq_ids(database: Path) -> list[str]:
    if not database.is_file():
        return []
    with sqlite3.connect(database, timeout=10) as connection:
        try:
            return [row[0] for row in connection.execute("SELECT rfq_id FROM rfqs")]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return []
            raise


def _contains_id(text: str, rfq_id: str) -> bool:
    return (
        re.search(rf"(?<![A-Za-z0-9._-]){re.escape(rfq_id)}(?![A-Za-z0-9._-])", text, re.IGNORECASE)
        is not None
    )


def _match_rfq(database: Path, message: EmailMessage) -> str:
    known = _known_rfq_ids(database)
    header = str(message.get("X-KiProd-RFQ-ID", "")).strip()
    if header and header not in known:
        raise ValueError(f"inbound email references unknown RFQ ID in header: {header}")
    subject = str(message.get("Subject", ""))
    in_subject = {rfq_id for rfq_id in known if _contains_id(subject, rfq_id)}
    candidates = in_subject | ({header} if header else set())
    if not candidates:
        raise ValueError("inbound email does not match a known RFQ ID")
    if len(candidates) > 1:
        raise ValueError("inbound email contains conflicting RFQ IDs")
    return next(iter(candidates))


def _safe_attachment_name(filename: str | None, index: int) -> str:
    candidate = (filename or f"attachment-{index}.bin").replace("\\", "/").split("/")[-1]
    safe = _SAFE_FILENAME.sub("_", candidate).strip(" .")
    return safe or f"attachment-{index}.bin"


def _attachments(message: EmailMessage) -> list[tuple[str, bytes]]:
    items: list[tuple[str, bytes]] = []
    used: set[str] = set()
    for index, part in enumerate(message.iter_attachments(), start=1):
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        name = _safe_attachment_name(part.get_filename(), index)
        stem, suffix = Path(name).stem, Path(name).suffix
        unique, duplicate = name, 1
        while unique.casefold() in used:
            duplicate += 1
            unique = f"{stem}-{duplicate}{suffix}"
        used.add(unique.casefold())
        items.append((unique, payload))
    return items


def import_reply(message_file: Path, database: Path, output_root: Path) -> InboxImport:
    """Match and safely capture one local .eml reply and its attachments."""
    if not message_file.is_file():
        raise ValueError(f"inbound email file does not exist: {message_file}")
    raw = message_file.read_bytes()
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise ValueError("inbound email exceeds the 50 MiB size limit")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    rfq_id = _match_rfq(database, message)
    status = get_rfq_status(database, rfq_id)
    if status is None or status.state not in {"sent", "acknowledged"}:
        raise ValueError(f"RFQ {rfq_id} is not awaiting a supplier reply")
    digest = hashlib.sha256(raw).hexdigest()
    with _connect(database) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT * FROM rfq_inbox_messages WHERE message_sha256 = ?", (digest,)
        ).fetchone()
    if existing is not None:
        if existing["rfq_id"] != rfq_id:
            raise ValueError("inbound email hash is already associated with another RFQ")
        if status.state == "sent":
            status = transition_rfq(database, rfq_id, "acknowledged")
        return InboxImport(
            rfq_id=rfq_id,
            message_sha256=digest,
            stored_message=str(existing["stored_path"]),
            attachments=json.loads(existing["attachment_names"]),
            state=status.state,
            imported_at=str(existing["imported_at"]),
        )

    attachments = _attachments(message)
    total_attachment_bytes = sum(len(payload) for _, payload in attachments)
    if total_attachment_bytes > _MAX_MESSAGE_BYTES:
        raise ValueError("inbound email attachments exceed the 50 MiB size limit")
    imported_at = datetime.now(UTC).isoformat()
    destination = output_root / rfq_id / digest[:16]
    if destination.exists():
        raise ValueError(f"inbox storage destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="kiprod-inbox-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "message"
        stage.mkdir()
        stored_message = stage / "reply.eml"
        stored_message.write_bytes(raw)
        for name, payload in attachments:
            (stage / name).write_bytes(payload)
        stage.rename(destination)
    attachment_names = [name for name, _ in attachments]
    final_message = destination / "reply.eml"
    try:
        with _connect(database) as connection:
            connection.execute(
                "INSERT INTO rfq_inbox_messages "
                "(message_sha256, rfq_id, source_path, stored_path, attachment_names, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    digest,
                    rfq_id,
                    str(message_file.resolve()),
                    str(final_message),
                    json.dumps(attachment_names),
                    imported_at,
                ),
            )
    except sqlite3.Error:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if status.state == "sent":
        status = transition_rfq(database, rfq_id, "acknowledged")
    return InboxImport(
        rfq_id=rfq_id,
        message_sha256=digest,
        stored_message=str(final_message),
        attachments=attachment_names,
        state=status.state,
        imported_at=imported_at,
    )
