# KiProd task list

## M1 — Ingest, export, and BOM CLI (complete)

- [x] Create isolated Git repository, project metadata, local developer scripts, and test fixture.
- [x] Discover a KiCad project and hash its relevant source files.
- [x] Read KiCad schematic S-expressions without importing KiCad.
- [x] Build a deterministic normalized BOM, honoring `in_bom` / DNP markers.
- [x] Write JSON and CSV artifacts with provenance; test source and generated-BOM paths.
- [x] Add a `kicad-cli` BOM export adapter; runtime availability is reported by `doctor`.
- [x] Reconcile imported BOM CSV MPN fields with schematic data by reference.
- [x] Detect named design variants from KiCad 10 project metadata.
- [x] Produce variant-specific normalized BOMs using `kicad-cli`'s authoritative export.
- [x] Add a golden normalized-BOM fixture for regression checks.
- [x] Add a golden fixture from a full real KiCad 10 project.

## M2 — Configuration and defaults policy (complete)

- [x] Layer built-in, user, and project TOML settings; expose config init/show/validate CLI commands.
- [x] Implement default / flag / error / guess / inherit / ignore policy resolution and non-interactive exit 3 handling.
- [x] Validate quantities, including add/remove and range shorthand.

## M3 — Plugin host and sourcing (in progress)

- [x] Validate typed plugin manifests and load adapters from plugin folders.
- [x] Discover plugins in precedence order and enforce declared network host access.
- [x] Add the manifest JSON Schema and validate custom field declarations.
- [x] Add a recorded supplier-search fixture.
- [x] Execute adapter methods in a timed subprocess with a restricted environment.
- [x] Keep adapter modules unloaded in the main process during plugin discovery.
- [x] Exercise adapter calls against recorded supplier fixtures.
- [x] Enforce network permissions through an HTTPS-only allowlisted HTTP client with fixture replay, caching, retries, and throttling.
- [x] Add a recorded catalog adapter example with validated offers and required source references.
- [x] Add CLI plugin discovery, health checks, and source-backed catalog search.
- [x] Add a production read-only JSON catalog protocol adapter with typed offer validation and recorded-fixture coverage; supplier-specific live connectors still require API terms, endpoint, and credential configuration.

## M4 — Analysis and reports (complete)

- [x] Calculate source-backed component landed costs with MOQ, order multiple, price breaks, attrition, and ancillary costs.
- [x] Rank landed costs by quantity and currency; emit Markdown comparison and landed-cost reports with evidence refs.
- [x] Add XLSX comparison workbook and normalized-BOM coverage-gap analysis.
- [x] Add cross-quantity supplier matrix and JSON comparison output for reproducible report regeneration.
- [x] Add full saved-run manifest and report regeneration command; archives preserve version/runtime provenance, reject replacement, and verify all saved input hashes before regeneration.

## M5 — Board and assembly (complete)

- [x] Extract copper layers, board thickness, outline bounds, minimum track, and drill metrics from PCB S-expressions.
- [x] Compare extracted fabrication metrics against declared supplier limits.
- [x] Extract stack-up layer types, material, thickness, and copper finish.
- [x] Export KiCad position CSV and map placement rows to common assembler column names.
- [x] Extract top/bottom placements, unique footprint count, SMD/THT counts, and smallest recognized package.
- [x] Compare placement count and unique parts to declared assembly supplier limits.
- [x] Extract BGA/QFN/LGA counts and finest observed pad pitch; compare them with declared assembly supplier limits.
- [x] Identify components explicitly marked `Programming` or `Requires Programming` and check supplier support.
- [x] Extract an explicit boards-per-panel value from supplied fabrication-note text files, retaining its source and rejecting conflicts.
- [x] Discover likely fabrication/panel notes by filename and parse text or PDF documentation; project board-file count and requested production quantities are already reported separately.
- [x] Support common fabrication, panel, assembly, manufacturing, and Gerber note filenames, with local OCR fallback for scanned PDFs.

## M6 — Signed email RFQs and inbox (in progress)

- [x] Package only explicitly selected files, generate a SHA-256 manifest, block scanner failures, sign with GPG, and verify archive contents/signature.
- [x] Add interactive approval records bound to exact package hashes and invalidate approval status when package bytes change.
- [x] Block package creation when staged text contains local home paths, the current username, or an explicit hidden-layer marker.
- [x] Inspect Office XML metadata/hidden sheets, PDF metadata/optional-content layers, and KiCad saved layer visibility.
- [x] Verify privacy checks do not flag the native KiCad 10 counter project fixture.
- [ ] Validate against additional real CAD exports and review false-positive rates.
- [x] Compose local email drafts with a verified signed package attached and record the RFQ in `awaiting_approval`.
- [x] Require approval of the exact saved email payload before the workflow can transition to `sent`.
- [x] Add SMTP/STARTTLS delivery of the exact approved email bytes; log failures and leave those RFQs retryable.
- [x] Match locally captured `.eml` replies by RFQ ID in subject/header, preserve the original, save sanitized attachments, and acknowledge the RFQ.
- [x] Parse CSV/XLSX quote tables into source-backed offer candidates with deterministic confidence and incomplete-row review queue.
- [x] Parse labeled-field PDF quotes into low-confidence candidates that always require human review.
- [x] Add local OCR fallback for scanned quote PDFs, with low confidence and mandatory careful review.
- [x] Poll Microsoft Graph/Gmail REST with bearer tokens through the HTTPS allowlist and import matched replies read-only.
- [x] Persist Graph/Gmail page cursors and advance only after the page is processed; reset after the final page.
- [x] Add a reproducible field-accuracy/precision/recall evaluation for quote fixtures with a 95% threshold and explicit optional-format skips.
- [x] Expand quote fixtures with a second supplier-style header layout and independently labeled expected fields.
- [ ] Validate quote extraction on independently reviewed real-world supplier samples.

## Later milestones

- [ ] M7: typed AI/review layer.
- [ ] M8–M10: GUI, KiCad launchers, and hardening.

## Recommended completion order

1. Finish M6's privacy and quote-parser validation using independently reviewed CAD exports and supplier quote samples; keep format-specific confidence/review rules in place.
2. Build M7 on the stable BOM, offer, and review-queue schemas, with all extracted commercial values remaining source-backed.
3. Build the M8 GUI, then M9 KiCad launchers, then M10 hardening and release checks.

M3–M5 are complete, and M4 provides durable analysis outputs. M6's real-world
validation needs representative sample files, so code-side work can continue while
those samples are collected.
