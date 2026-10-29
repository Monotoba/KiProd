from __future__ import annotations

import hashlib
import smtplib
import ssl
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path

from kiprod.rfq.approval import has_hash_approval
from kiprod.rfq.workflow import (
    RFQStatus,
    get_rfq_status,
    record_delivery_attempt,
    transition_rfq,
)


def send_approved_rfq(
    database: Path,
    rfq_id: str,
    smtp_host: str,
    *,
    smtp_port: int = 587,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 30,
) -> RFQStatus:
    """Send exact approved RFC 5322 bytes over validated SMTP STARTTLS."""
    if not smtp_host.strip() or "\r" in smtp_host or "\n" in smtp_host:
        raise ValueError("SMTP host must be non-empty and single-line")
    if not 1 <= smtp_port <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535")
    if (username is None) != (password is None):
        raise ValueError("SMTP username and password must be provided together")
    status = get_rfq_status(database, rfq_id)
    if status is None:
        raise ValueError(f"unknown RFQ ID: {rfq_id}")
    if status.state != "awaiting_approval":
        raise ValueError(f"RFQ {rfq_id} is {status.state}, expected awaiting_approval")
    payload = Path(status.payload_path)
    if not payload.is_file():
        raise ValueError("RFQ email is not approved in its current exact form")
    raw_message = payload.read_bytes()
    digest = hashlib.sha256(raw_message).hexdigest()
    if digest != status.payload_sha256 or not has_hash_approval(digest, database):
        raise ValueError("RFQ email is not approved in its current exact form")
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    if message.get("X-KiProd-RFQ-ID") != rfq_id:
        raise ValueError("saved email RFQ ID does not match workflow record")
    if message.get("Cc") or message.get("Bcc"):
        raise ValueError("RFQ email must have exactly one visible To recipient")
    sender = getaddresses([str(message.get("From", ""))])
    recipients = getaddresses([str(message.get("To", ""))])
    if len(sender) != 1 or not sender[0][1] or len(recipients) != 1 or not recipients[0][1]:
        raise ValueError("saved RFQ email must have one valid From and To address")
    sender_address = sender[0][1]
    recipient_address = recipients[0][1]

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as client:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            if username is not None and password is not None:
                client.login(username, password)
            refused = client.sendmail(sender_address, [recipient_address], raw_message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    except (OSError, smtplib.SMTPException) as exc:
        record_delivery_attempt(database, rfq_id, succeeded=False, detail=str(exc))
        raise RuntimeError(f"SMTP delivery failed; RFQ remains retryable: {exc}") from exc

    try:
        updated = transition_rfq(database, rfq_id, "sent")
    except ValueError as exc:
        record_delivery_attempt(
            database,
            rfq_id,
            succeeded=True,
            detail=f"SMTP accepted the message but state update failed: {exc}",
        )
        raise RuntimeError(
            "SMTP accepted the message, but the local RFQ state could not be updated"
        ) from exc
    record_delivery_attempt(database, rfq_id, succeeded=True, detail="SMTP accepted message")
    return updated
