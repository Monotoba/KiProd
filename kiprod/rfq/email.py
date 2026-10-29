from __future__ import annotations

from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

from kiprod.rfq.package import verify_package


def create_email_draft(
    *,
    rfq_id: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    package: Path,
    output: Path,
) -> Path:
    """Save a verified package as a local RFC 5322 email draft; do not transmit it."""
    if not verify_package(package):
        raise ValueError("RFQ package must contain at least one verified file")
    for label, address in (("sender", sender), ("recipient", recipient)):
        parsed = parseaddr(address)[1]
        if not parsed or "@" not in parsed or parsed != address:
            raise ValueError(f"invalid email {label}: {address!r}")
    if not subject.strip() or "\n" in subject or "\r" in subject:
        raise ValueError("email subject must be non-empty and single-line")
    if not rfq_id.strip() or any(character.isspace() for character in rfq_id):
        raise ValueError("RFQ ID must be non-empty and contain no whitespace")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.partition("@")[2])
    message["X-KiProd-RFQ-ID"] = rfq_id
    message.set_content(body)
    message.add_attachment(
        package.read_bytes(),
        maintype="application",
        subtype="zip",
        filename=package.name,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(message.as_bytes(policy=SMTP))
    return output
