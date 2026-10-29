from __future__ import annotations

import base64
import json
import smtplib
import sqlite3
import subprocess
import zipfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import pytest

import kiprod.rfq.delivery as rfq_delivery
import kiprod.rfq.package as rfq_package
import kiprod.rfq.privacy as rfq_privacy
from kiprod.net.http import HttpClient, HttpResponse
from kiprod.rfq.approval import approve_package, has_current_approval, package_sha256
from kiprod.rfq.email import create_email_draft
from kiprod.rfq.inbox import import_reply
from kiprod.rfq.mailbox import _gmail_url, _graph_url, poll_mailbox
from kiprod.rfq.privacy import scan_privacy
from kiprod.rfq.workflow import (
    get_mailbox_cursor,
    get_rfq_status,
    register_email_draft,
    transition_rfq,
)


def _mock_tools(monkeypatch: pytest.MonkeyPatch, *, scan_status: int = 0) -> None:
    monkeypatch.setattr(
        rfq_package.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"gpg", "clamscan"} else None,
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--local-user" in command:
            signature = Path(command[command.index("--output") + 1])
            signature.write_bytes(b"mock detached signature")
            return subprocess.CompletedProcess(command, 0, "", "")
        status = scan_status if "--no-summary" in command else 0
        return subprocess.CompletedProcess(command, status, "", "")

    monkeypatch.setattr(rfq_package.subprocess, "run", run)


def test_package_contains_explicit_files_manifest_and_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\nR1,1\n", encoding="utf-8")
    output = tmp_path / "out" / "package.zip"

    result = rfq_package.build_package({"bom.csv": source}, output, "test-key")

    assert result == output
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"bom.csv", "MANIFEST.sha256", "MANIFEST.sha256.sig"}
        manifest = archive.read("MANIFEST.sha256").decode()
        assert "13  bom.csv" in manifest
    assert rfq_package.verify_package(output) == ["bom.csv"]


def test_tampered_package_file_fails_manifest_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "drawing.bin"
    source.write_bytes(b"original")
    output = tmp_path / "package.zip"
    rfq_package.build_package({"drawing.bin": source}, output, "test-key")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(tampered, "w") as changed:
        for name in original.namelist():
            payload = b"changed" if name == "drawing.bin" else original.read(name)
            changed.writestr(name, payload)

    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        rfq_package.verify_package(tampered)


def test_scanner_failure_blocks_package_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch, scan_status=1)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="malware detected"):
        rfq_package.build_package({"bom.csv": source}, tmp_path / "package.zip", "test-key")
    assert not (tmp_path / "package.zip").exists()


def test_privacy_scan_detects_local_paths_usernames_and_hidden_layers(tmp_path: Path) -> None:
    content = tmp_path / "board.kicad_pcb"
    content.write_text(
        '(comment "/home/alice/design.kicad_pcb")\n(layer "User.Drawings" user hide)',
        encoding="utf-8",
    )

    findings = scan_privacy(
        tmp_path,
        sensitive_roots=[Path("/home/alice")],
        usernames=["alice"],
    )

    assert findings == [
        "board.kicad_pcb: embedded local filesystem path",
        "board.kicad_pcb: embedded local username",
        "board.kicad_pcb: hidden layer declaration",
    ]


def test_privacy_scan_reads_office_metadata_and_hidden_sheets(tmp_path: Path) -> None:
    office = tmp_path / "supplier-quote.xlsx"
    with zipfile.ZipFile(office, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            "<core><creator>alice</creator><description>/home/alice/quote.xlsx</description></core>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook><sheet name="Hidden Data" state="veryHidden"/></workbook>',
        )

    findings = scan_privacy(
        tmp_path,
        sensitive_roots=[Path("/home/alice")],
        usernames=["alice"],
    )

    assert findings == [
        "supplier-quote.xlsx: embedded local filesystem path",
        "supplier-quote.xlsx: embedded local username",
        "supplier-quote.xlsx: hidden Office document content",
    ]


def test_privacy_scan_reads_pdf_metadata_and_optional_content_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "drawing.pdf"
    pdf.write_bytes(b"%PDF-1.4 /OCProperties << /OFF [5 0 R] >>")
    monkeypatch.setattr(rfq_privacy.shutil, "which", lambda _: "/usr/bin/pdfinfo")
    monkeypatch.setattr(
        rfq_privacy.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "Author: alice\n", ""),
    )

    findings = scan_privacy(tmp_path, usernames=["alice"])

    assert findings == [
        "drawing.pdf: embedded local username",
        "drawing.pdf: hidden PDF optional-content layer",
    ]


def test_privacy_scan_blocks_pdfs_when_metadata_tool_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "quote.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(rfq_privacy.shutil, "which", lambda _: None)

    assert scan_privacy(tmp_path, usernames=[]) == [
        "quote.pdf: PDF metadata inspection requires local pdfinfo"
    ]


def test_privacy_scan_detects_kicad_hidden_layer_visibility(tmp_path: Path) -> None:
    preferences = tmp_path / "board.kicad_prl"
    preferences.write_text(
        '{"board":{"visible_layers":"ffffffff_fffffffe_ffffffff_ffffffff"}}',
        encoding="utf-8",
    )
    assert scan_privacy(tmp_path, usernames=[]) == [
        "board.kicad_prl: hidden KiCad layer visibility state"
    ]


def test_privacy_scan_blocks_package_before_malware_scan_or_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "board.kicad_pcb"
    source.write_text("PCB data", encoding="utf-8")
    monkeypatch.setattr(rfq_package, "scan_privacy", lambda _: ["unsafe content"])
    monkeypatch.setattr(
        rfq_package,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("external scanner/signing must not run"),
    )

    with pytest.raises(RuntimeError, match="privacy scan blocked"):
        rfq_package.build_package({"board.kicad_pcb": source}, tmp_path / "package.zip", "test-key")


def test_approval_is_bound_to_exact_package_bytes(tmp_path: Path) -> None:
    package = tmp_path / "package.zip"
    database = tmp_path / "state.sqlite"
    package.write_bytes(b"signed archive bytes")
    digest = package_sha256(package)

    record = approve_package(package, database, "operator", expected_hash=digest)

    assert record.package_sha256 == digest
    assert record.user == "operator"
    assert has_current_approval(package, database)
    package.write_bytes(b"changed archive bytes")
    assert not has_current_approval(package, database)


def test_approval_rejects_package_changed_after_hash_review(tmp_path: Path) -> None:
    package = tmp_path / "package.zip"
    package.write_bytes(b"new package")
    with pytest.raises(ValueError, match="changed"):
        approve_package(package, tmp_path / "state.sqlite", "operator", expected_hash="0" * 64)


def test_email_draft_attaches_verified_package_and_waits_for_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\nR1,1\n", encoding="utf-8")
    package = rfq_package.build_package({"bom.csv": source}, tmp_path / "package.zip", "test-key")
    draft = create_email_draft(
        rfq_id="KP-board-20261029-1",
        sender="buyer@example.test",
        recipient="quotes@example.test",
        subject="RFQ KP-board-20261029-1",
        body="Please quote the attached package.",
        package=package,
        output=tmp_path / "email.eml",
    )
    message = BytesParser(policy=policy.default).parsebytes(draft.read_bytes())
    attachments = list(message.iter_attachments())
    assert message["X-KiProd-RFQ-ID"] == "KP-board-20261029-1"
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "package.zip"
    database = tmp_path / "state.sqlite"
    status = register_email_draft(database, "KP-board-20261029-1", "quotes@example.test", draft)
    assert status.state == "awaiting_approval"
    assert get_rfq_status(database, status.rfq_id) == status
    with pytest.raises(ValueError, match="approval"):
        transition_rfq(database, status.rfq_id, "sent")


def test_rfq_can_enter_sent_only_after_approval_of_saved_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    package_source = tmp_path / "bom.csv"
    package_source.write_text("Ref,Qty\nR1,1\n", encoding="utf-8")
    package = rfq_package.build_package(
        {"bom.csv": package_source}, tmp_path / "package.zip", "test-key"
    )
    draft = create_email_draft(
        rfq_id="KP-test-1",
        sender="buyer@example.test",
        recipient="quotes@example.test",
        subject="RFQ KP-test-1",
        body="Quote requested.",
        package=package,
        output=tmp_path / "rfq.eml",
    )
    database = tmp_path / "state.sqlite"
    register_email_draft(database, "KP-test-1", "quotes@example.test", draft)
    approve_package(draft, database, "operator")

    assert transition_rfq(database, "KP-test-1", "sent").state == "sent"
    draft.write_bytes(draft.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="invalid RFQ state transition"):
        transition_rfq(database, "KP-test-1", "sent")


def test_changed_email_cannot_use_its_old_approval_to_enter_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_tools(monkeypatch)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\n", encoding="utf-8")
    package = rfq_package.build_package({"bom.csv": source}, tmp_path / "pkg.zip", "test-key")
    draft = create_email_draft(
        rfq_id="KP-test-2",
        sender="buyer@example.test",
        recipient="quotes@example.test",
        subject="RFQ KP-test-2",
        body="Quote this.",
        package=package,
        output=tmp_path / "request.eml",
    )
    database = tmp_path / "state.sqlite"
    register_email_draft(database, "KP-test-2", "quotes@example.test", draft)
    approve_package(draft, database, "operator")
    draft.write_bytes(draft.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="exact saved email"):
        transition_rfq(database, "KP-test-2", "sent")


class FakeSMTP:
    instances: list[FakeSMTP] = []
    fail: bool = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.raw_message: bytes | None = None
        self.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def ehlo(self) -> None:
        pass

    def starttls(self, *, context: object) -> None:
        assert context is not None

    def login(self, username: str, password: str) -> None:
        assert username == "account"
        assert password == "secret"

    def sendmail(self, sender: str, recipients: list[str], message: bytes) -> dict[str, object]:
        assert sender == "buyer@example.test"
        assert recipients == ["quotes@example.test"]
        self.raw_message = message
        if self.fail:
            raise smtplib.SMTPConnectError(421, b"temporary failure")
        return {}


def _approved_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rfq_id: str
) -> tuple[Path, Path, bytes]:
    _mock_tools(monkeypatch)
    source = tmp_path / f"{rfq_id}.csv"
    source.write_text("Ref,Qty\nR1,1\n", encoding="utf-8")
    package = rfq_package.build_package(
        {source.name: source}, tmp_path / f"{rfq_id}.zip", "test-key"
    )
    draft = create_email_draft(
        rfq_id=rfq_id,
        sender="buyer@example.test",
        recipient="quotes@example.test",
        subject=f"RFQ {rfq_id}",
        body="Quote request.",
        package=package,
        output=tmp_path / f"{rfq_id}.eml",
    )
    database = tmp_path / "state.sqlite"
    register_email_draft(database, rfq_id, "quotes@example.test", draft)
    approve_package(draft, database, "operator")
    return database, draft, draft.read_bytes()


def test_send_uses_tls_and_transmits_exact_approved_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail = False
    monkeypatch.setattr(rfq_delivery.smtplib, "SMTP", FakeSMTP)
    database, draft, approved_bytes = _approved_draft(tmp_path, monkeypatch, "KP-send-1")

    status = rfq_delivery.send_approved_rfq(
        database,
        "KP-send-1",
        "smtp.example.test",
        username="account",
        password="secret",
    )

    assert status.state == "sent"
    assert FakeSMTP.instances[0].raw_message == approved_bytes
    assert FakeSMTP.instances[0].host == "smtp.example.test"
    assert draft.read_bytes() == approved_bytes
    with sqlite3.connect(database) as connection:
        attempt = connection.execute(
            "SELECT succeeded FROM rfq_delivery_attempts WHERE rfq_id = ?", ("KP-send-1",)
        ).fetchone()
    assert attempt == (1,)


def test_unapproved_email_never_connects_to_smtp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeSMTP.instances = []
    monkeypatch.setattr(rfq_delivery.smtplib, "SMTP", FakeSMTP)
    _mock_tools(monkeypatch)
    source = tmp_path / "bom.csv"
    source.write_text("Ref,Qty\n", encoding="utf-8")
    package = rfq_package.build_package({"bom.csv": source}, tmp_path / "pkg.zip", "test-key")
    draft = create_email_draft(
        rfq_id="KP-unapproved-1",
        sender="buyer@example.test",
        recipient="quotes@example.test",
        subject="RFQ KP-unapproved-1",
        body="Quote this.",
        package=package,
        output=tmp_path / "request.eml",
    )
    database = tmp_path / "state.sqlite"
    register_email_draft(database, "KP-unapproved-1", "quotes@example.test", draft)

    with pytest.raises(ValueError, match="not approved"):
        rfq_delivery.send_approved_rfq(database, "KP-unapproved-1", "smtp.example.test")
    assert FakeSMTP.instances == []


def test_smtp_failure_is_logged_and_rfq_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail = True
    monkeypatch.setattr(rfq_delivery.smtplib, "SMTP", FakeSMTP)
    database, _, _ = _approved_draft(tmp_path, monkeypatch, "KP-send-2")

    with pytest.raises(RuntimeError, match="remains retryable"):
        rfq_delivery.send_approved_rfq(database, "KP-send-2", "smtp.example.test")

    assert get_rfq_status(database, "KP-send-2").state == "awaiting_approval"
    with sqlite3.connect(database) as connection:
        attempt = connection.execute(
            "SELECT succeeded FROM rfq_delivery_attempts WHERE rfq_id = ?", ("KP-send-2",)
        ).fetchone()
    assert attempt == (0,)


def test_import_reply_matches_subject_saves_attachment_and_acknowledges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _, _ = _approved_draft(tmp_path, monkeypatch, "KP-inbox-1")
    transition_rfq(database, "KP-inbox-1", "sent")
    reply = EmailMessage()
    reply["From"] = "quotes@example.test"
    reply["To"] = "buyer@example.test"
    reply["Subject"] = "Re: RFQ KP-inbox-1 — pricing attached"
    reply.set_content("Please see the quote.")
    reply.add_attachment(
        b"part,qty,unit_price\nX1,10,1.25\n",
        maintype="text",
        subtype="csv",
        filename="../../quote.csv",
    )
    source = tmp_path / "supplier-reply.eml"
    source.write_bytes(reply.as_bytes())

    imported = import_reply(source, database, tmp_path / "replies")

    assert imported.rfq_id == "KP-inbox-1"
    assert imported.state == "acknowledged"
    assert imported.attachments == ["quote.csv"]
    assert (Path(imported.stored_message).parent / "quote.csv").read_bytes().startswith(b"part,qty")
    assert get_rfq_status(database, "KP-inbox-1").state == "acknowledged"
    duplicate = import_reply(source, database, tmp_path / "replies")
    assert duplicate == imported


def test_import_reply_matches_rfq_header_when_subject_has_no_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _, _ = _approved_draft(tmp_path, monkeypatch, "KP-inbox-2")
    transition_rfq(database, "KP-inbox-2", "sent")
    reply = EmailMessage()
    reply["X-KiProd-RFQ-ID"] = "KP-inbox-2"
    reply["Subject"] = "Re: Your quotation"
    reply.set_content("Received")
    source = tmp_path / "reply.eml"
    source.write_bytes(reply.as_bytes())

    imported = import_reply(source, database, tmp_path / "replies")

    assert imported.rfq_id == "KP-inbox-2"
    assert imported.state == "acknowledged"


def test_import_reply_rejects_conflicting_rfq_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _, _ = _approved_draft(tmp_path, monkeypatch, "KP-inbox-3")
    _approved_draft(tmp_path, monkeypatch, "KP-inbox-4")
    transition_rfq(database, "KP-inbox-3", "sent")
    transition_rfq(database, "KP-inbox-4", "sent")
    reply = EmailMessage()
    reply["X-KiProd-RFQ-ID"] = "KP-inbox-3"
    reply["Subject"] = "Re: KP-inbox-4"
    reply.set_content("Conflicting reference")
    source = tmp_path / "reply.eml"
    source.write_bytes(reply.as_bytes())

    with pytest.raises(ValueError, match="conflicting"):
        import_reply(source, database, tmp_path / "replies")


@pytest.mark.parametrize("name", ["../secret.txt", "/etc/passwd", "folder\\file.txt"])
def test_package_rejects_unsafe_archive_paths(name: str, tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        rfq_package.build_package({name: source}, tmp_path / "package.zip", "test-key")


def _sent_rfq_for_mailbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rfq_id: str) -> Path:
    database, _, _ = _approved_draft(tmp_path, monkeypatch, rfq_id)
    transition_rfq(database, rfq_id, "sent")
    return database


def _reply_bytes(rfq_id: str) -> bytes:
    reply = EmailMessage()
    reply["From"] = "quotes@example.test"
    reply["To"] = "buyer@example.test"
    reply["Subject"] = f"Re: RFQ {rfq_id}"
    reply.set_content("We received your RFQ.")
    return reply.as_bytes()


def test_graph_mailbox_poll_imports_matching_messages_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rfq_id = "KP-graph-1"
    database = _sent_rfq_for_mailbox(tmp_path, monkeypatch, rfq_id)
    raw = _reply_bytes(rfq_id)
    listing_url = _graph_url(10)
    raw_url = "https://graph.microsoft.com/v1.0/me/messages/message%2F1/$value"
    http = HttpClient(
        {"graph.microsoft.com"},
        fixtures={
            ("GET", listing_url): HttpResponse(
                200,
                {},
                json.dumps(
                    {
                        "value": [
                            {
                                "id": "message/1",
                                "subject": f"Re: {rfq_id}",
                                "internetMessageHeaders": [],
                            },
                            {"id": "unrelated", "subject": "Hello"},
                        ]
                    }
                ).encode(),
            ),
            ("GET", raw_url): HttpResponse(200, {"Content-Type": "message/rfc822"}, raw),
        },
    )

    result = poll_mailbox("graph", "token", database, tmp_path / "replies", limit=10, client=http)

    assert result.checked == 1
    assert len(result.imported) == 1
    assert result.imported[0].rfq_id == rfq_id
    assert result.imported[0].state == "acknowledged"


def test_gmail_mailbox_poll_decodes_raw_message_and_imports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rfq_id = "KP-gmail-1"
    database = _sent_rfq_for_mailbox(tmp_path, monkeypatch, rfq_id)
    raw = _reply_bytes(rfq_id)
    listing_url = _gmail_url(10)
    raw_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-1?format=raw"
    http = HttpClient(
        {"gmail.googleapis.com"},
        fixtures={
            ("GET", listing_url): HttpResponse(
                200, {}, json.dumps({"messages": [{"id": "msg-1"}]}).encode()
            ),
            ("GET", raw_url): HttpResponse(
                200,
                {},
                json.dumps({"raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}).encode(),
            ),
        },
    )

    result = poll_mailbox("gmail", "token", database, tmp_path / "replies", limit=10, client=http)

    assert result.checked == 1
    assert result.imported[0].rfq_id == rfq_id
    assert result.imported[0].state == "acknowledged"


def test_mailbox_pagination_cursor_advances_and_resets_after_last_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rfq_id = "KP-pages-1"
    database = _sent_rfq_for_mailbox(tmp_path, monkeypatch, rfq_id)
    raw = _reply_bytes(rfq_id)
    first_url = _gmail_url(1)
    second_url = _gmail_url(1, "page-2")
    raw_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-1?format=raw"
    http = HttpClient(
        {"gmail.googleapis.com"},
        fixtures={
            ("GET", first_url): HttpResponse(
                200,
                {},
                json.dumps({"messages": [{"id": "msg-1"}], "nextPageToken": "page-2"}).encode(),
            ),
            ("GET", raw_url): HttpResponse(
                200,
                {},
                json.dumps({"raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}).encode(),
            ),
            ("GET", second_url): HttpResponse(200, {}, json.dumps({"messages": []}).encode()),
        },
    )

    first = poll_mailbox("gmail", "token", database, tmp_path / "replies", limit=1, client=http)
    assert first.more_available
    assert get_mailbox_cursor(database, "gmail") == "page-2"

    second = poll_mailbox("gmail", "token", database, tmp_path / "replies", limit=1, client=http)
    assert not second.more_available
    assert get_mailbox_cursor(database, "gmail") is None
