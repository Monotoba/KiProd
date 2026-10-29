# KiProd

KiProd creates a traceable production package from a KiCad project: a normalized
BOM, production review findings, supplier quotes, and comparison reports.

Milestones **M1–M5** are complete; **M6** and **M7** are in progress.
The CLI supports offline BOM/configuration work, board and assembly analysis, local
RFQ packaging, approval-gated SMTP delivery, and Graph/Gmail inbox polling. The
generic catalog protocol, typed AI review contracts, an OpenAI-compatible model
adapter, native OpenAI and Anthropic adapters, and role-based request budgets are
available; supplier-specific live adapters and the GUI have not shipped. Live email,
mailbox, and model operations require user-provided credentials and configuration.

## Quick start

```bash
./scripts/setup.sh
./scripts/run.sh bom --project tests/projects/basic
./scripts/test.sh
```

The BOM command writes `docs/production/bom/bom.normalized.json` and `bom.csv`
in the selected KiCad project. Pass `--output-dir DIR` to write elsewhere.

To enrich schematic data from a reviewed CSV, use `--import-bom reviewed.csv`.
`kiprod export-bom board.kicad_sch -o exported.csv` delegates CSV export to a
locally installed `kicad-cli` without making it a core dependency.

Use `kiprod project --project DIR` to discover named KiCad 10 design variants.
`kiprod bom --project DIR --variant NAME` uses KiCad's own variant-aware BOM
export, so variant DNP and field overrides are applied before normalization.

`kiprod board --project DIR --fab-notes fab-notes.txt` includes an explicitly
documented boards-per-panel count in the board metrics. It discovers likely
fabrication and panelization notes by filename; `--fab-notes` adds files explicitly.
Text and PDF notes are supported, with PDF text extraction requiring `pdftotext`.
Scanned PDFs fall back to local OCR with `pdftoppm` and `tesseract`. Conflicting
counts fail rather than silently choosing one. Without a supplied or discovered
note, the value remains unknown.

Create a local signed RFQ archive from explicitly selected files with
`kiprod rfq package bom.csv cpl.csv --output package.zip --signing-key KEY_ID`,
then verify it with `kiprod rfq verify package.zip`. This requires local `clamscan`
and `gpg` executables and never sends the package. Including PDFs also requires
`pdfinfo` so document metadata can be checked.
Package staging also blocks text files containing the current user's home path or
username and files with explicit hidden-layer markers.
Run `kiprod rfq scan-privacy bom.csv drawing.pdf` to preflight explicitly selected
files without creating a package; it exits 3 when a finding blocks packaging.
Create a local message draft with `kiprod rfq draft KP-board-20261029-1 package.zip
--to quotes@example.com --from buyer@example.com --subject "RFQ KP-board-20261029-1"
--body request.txt --output request.eml`. It verifies and attaches the signed archive,
then records the RFQ as `awaiting_approval`; it does not send email. Approve the exact
message with `kiprod rfq approve request.eml`; the CLI shows its SHA-256 before
confirmation and stores the approval in `.kiprod/state.sqlite`. Approval status becomes
invalid if the message bytes change. `kiprod rfq status KP-board-20261029-1` shows its
current state.
After approval, `kiprod rfq send KP-board-20261029-1 --smtp-host smtp.example.com`
sends the exact approved `.eml` bytes over certificate-validated STARTTLS. Add
`--username ACCOUNT` to authenticate; the password is read from the
`KIPROD_SMTP_PASSWORD` environment variable (or the variable named by
`--password-env`). Delivery failures are recorded and leave the RFQ retryable.
To capture an exported supplier reply without connecting to a mailbox, run
`kiprod rfq import-reply reply.eml`. KiProd matches the RFQ ID from the subject or
`X-KiProd-RFQ-ID` header, stores the original message and sanitized attachments under
`.kiprod/replies/`, and moves a sent RFQ to `acknowledged`.
Poll Microsoft Graph or Gmail REST with a bearer token already obtained by the user:
`kiprod rfq poll-mailbox graph` or `kiprod rfq poll-mailbox gmail`. The token is read
from `KIPROD_MAILBOX_TOKEN`; polling is read-only and uses the allowlisted HTTPS client.
Page cursors persist in the local state database; rerun the command while additional
pages are available to continue the sweep.
Parse structured CSV/XLSX quote attachments with
`kiprod rfq parse-quote quote.csv --supplier-id supplier-a --output offers.json`.
The output keeps source row references, candidate confidence, and incomplete rows in a
review queue; XLSX parsing uses the optional `reports` dependency. PDFs are parsed only
when quote fields use explicit `Label: value` lines. Scanned PDFs use local OCR when
`pdftoppm` and `tesseract` are available. PDF and OCR candidates always enter the
human review queue, with OCR candidates marked for careful review.
Run the labeled CSV/PDF/XLSX fixture evaluation with `./scripts/eval_quotes.sh`.
It reports field accuracy, precision, recall, review counts, and skipped optional formats;
the default accuracy threshold is 95%.

Project and supplier plugins live under
`docs/production/quotes/config/suppliers/`. Use `kiprod plugins list` to inspect
available plugins, `kiprod plugins test PLUGIN_ID` for an isolated health check,
and `kiprod quote MPN --plugin PLUGIN_ID` to query a catalog plugin.

## Development

`TASKS.md` is the maintained implementation plan. The detailed product
specification is retained in `docs/`. See `AGENTS.md` for non-negotiable
architecture and safety constraints.

Synthetic manual-test inputs for CSV, XLSX, PDF, and privacy preflight are in
[`examples/testing_inputs/`](examples/testing_inputs/README.md). They contain
fictional data and include commands for exercising the CLI.
