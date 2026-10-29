from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode

from pydantic import BaseModel, Field

from kiprod.net.http import HttpClient, HttpError
from kiprod.rfq.inbox import InboxImport, import_reply, known_rfq_ids

_PROVIDERS = {
    "graph": "graph.microsoft.com",
    "gmail": "gmail.googleapis.com",
}


class MailboxPollResult(BaseModel):
    provider: str
    checked: int
    imported: list[InboxImport] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _contains_known_id(text: str, known: list[str]) -> bool:
    return any(
        re.search(rf"(?<![A-Za-z0-9._-]){re.escape(rfq_id)}(?![A-Za-z0-9._-])", text) is not None
        for rfq_id in known
    )


def _graph_url(limit: int) -> str:
    query = urlencode(
        {
            "$filter": "isRead eq false",
            "$select": "id,subject,internetMessageHeaders",
            "$top": str(limit),
        }
    )
    return f"https://graph.microsoft.com/v1.0/me/messages?{query}"


def _gmail_url(limit: int) -> str:
    query = urlencode({"q": "in:inbox", "maxResults": str(limit)})
    return f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{query}"


def _graph_candidates(response: object, known: list[str]) -> list[dict[str, object]]:
    if not isinstance(response, dict) or not isinstance(response.get("value"), list):
        raise ValueError("Microsoft Graph returned an invalid messages response")
    candidates: list[dict[str, object]] = []
    for item in response["value"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        subject = str(item.get("subject", ""))
        headers = item.get("internetMessageHeaders", [])
        header_text = ""
        if isinstance(headers, list):
            header_text = " ".join(
                str(header.get("value", ""))
                for header in headers
                if isinstance(header, dict)
                and str(header.get("name", "")).casefold() == "x-kiprod-rfq-id"
            )
        if _contains_known_id(f"{subject} {header_text}", known):
            candidates.append(item)
    return candidates


def _gmail_ids(response: object) -> list[str]:
    if not isinstance(response, dict):
        raise ValueError("Gmail returned an invalid messages response")
    items = response.get("messages", [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("Gmail returned an invalid messages list")
    return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]


def poll_mailbox(
    provider: str,
    access_token: str,
    database: Path,
    output_root: Path,
    *,
    limit: int = 50,
    client: HttpClient | None = None,
) -> MailboxPollResult:
    """Read a page of messages via Microsoft Graph or Gmail REST and import RFQ replies."""
    key = provider.casefold()
    host = _PROVIDERS.get(key)
    if host is None:
        raise ValueError("mailbox provider must be 'graph' or 'gmail'")
    if not access_token.strip():
        raise ValueError("mailbox access token must be non-empty")
    if not 1 <= limit <= 100:
        raise ValueError("mailbox poll limit must be between 1 and 100")
    http = client or HttpClient({host}, timeout=20, retries=1)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    known = known_rfq_ids(database)
    result = MailboxPollResult(provider=key, checked=0)
    if not known:
        return result
    try:
        listing_url = _graph_url(limit) if key == "graph" else _gmail_url(limit)
        listing_response = http.get(listing_url, headers=headers)
        if listing_response.status != 200:
            raise HttpError(f"mailbox API returned HTTP {listing_response.status}")
        listing = listing_response.json()
        if key == "graph":
            message_ids = [str(item["id"]) for item in _graph_candidates(listing, known)]
        else:
            message_ids = _gmail_ids(listing)
    except (HttpError, ValueError, json.JSONDecodeError) as exc:
        result.errors.append(str(exc))
        return result
    result.checked = len(message_ids)

    with TemporaryDirectory(prefix="kiprod-mailbox-") as temporary:
        directory = Path(temporary)
        for message_id in message_ids:
            encoded_id = quote(message_id, safe="")
            if key == "graph":
                raw_url = f"https://{host}/v1.0/me/messages/{encoded_id}/$value"
            else:
                raw_url = f"https://{host}/gmail/v1/users/me/messages/{encoded_id}?format=raw"
            try:
                response = http.get(raw_url, headers=headers)
                if response.status != 200:
                    raise HttpError(f"mailbox message fetch returned HTTP {response.status}")
                if key == "graph":
                    raw = response.body
                else:
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get("raw"), str):
                        raise ValueError("Gmail returned a message without raw content")
                    encoded = payload["raw"]
                    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                message_file = directory / f"{len(result.imported)}-{encoded_id[:40]}.eml"
                message_file.write_bytes(raw)
                imported = import_reply(
                    message_file,
                    database,
                    output_root,
                    source_label=f"{key}:{message_id}",
                )
                result.imported.append(imported)
            except (OSError, HttpError, ValueError, json.JSONDecodeError) as exc:
                result.skipped.append(f"{key}:{message_id}: {exc}")
    return result
