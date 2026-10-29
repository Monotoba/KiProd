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

## M3 — Plugin host and sourcing (complete)

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
- [x] Add a local privacy preflight command for selected RFQ files with blocking exit status.
- [x] Validate clean-project false-positive rate against four installed KiCad template projects (12 native project, schematic, and board files; 0 findings). Results and scope limits: `docs/PRIVACY_VALIDATION.md`.
- [x] Compose local email drafts with a verified signed package attached and record the RFQ in `awaiting_approval`.
- [x] Require approval of the exact saved email payload before the workflow can transition to `sent`.
- [x] Add SMTP/STARTTLS delivery of the exact approved email bytes; log failures and leave those RFQs retryable.
- [x] Match locally captured `.eml` replies by RFQ ID in subject/header, preserve the original, save sanitized attachments, and acknowledge the RFQ.
- [x] Parse CSV/XLSX quote tables into source-backed offer candidates with deterministic confidence and incomplete-row review queue.
- [x] Parse labeled-field PDF quotes into low-confidence candidates that always require human review.
- [x] Add local OCR fallback for scanned quote PDFs, with low confidence and mandatory careful review.
- [x] Poll Microsoft Graph/Gmail REST with bearer tokens through the HTTPS allowlist and import matched replies read-only.
- [x] Persist Graph/Gmail page cursors and advance only after the page is processed; reset after the final page.
- [x] Add a reproducible field-accuracy/precision/recall evaluation for quote fixtures with a 95% threshold, explicit optional-format skips, and enforced fixture review-policy expectations.
- [x] Expand quote fixtures with alternate supplier-style headers and title/metadata preambles for CSV/XLSX, with independently labeled expected fields.
- [ ] Validate quote extraction on independently reviewed real-world supplier samples.

## M7 — Typed AI and review layer (complete)

- [x] Define a provider-neutral LLM protocol with typed messages and result metadata.
- [x] Add deterministic BOM findings and a no-provider fallback.
- [x] Validate AI review proposals against a strict schema, require known BOM line citations, and retain provider/model/prompt provenance.
- [x] Minimize review payloads to BOM identity fields and require local providers for confidential projects.
- [x] Add an OpenAI-compatible chat-completions adapter for HTTPS providers and explicitly allowed loopback model servers.
- [x] Add native OpenAI Responses and Anthropic Messages adapters with structured JSON output and usage metadata.
- [x] Add role-based provider selection, local-only role enforcement, run token/cost caps, dry-run planning, and in-memory content-hash caching.
- [x] Add versioned Markdown prompt files with validated front matter and ordered override directories.
- [x] Add labeled BOM review evaluation with typed-schema success rate, exact finding precision/recall/F1, citation grounding, and CLI support for configured providers.

## M8 — Standalone desktop GUI (in progress)

- [x] Add an optional PySide6 desktop entry point and GUI setup script.
- [x] Add project selection and a run bar with project/variant context and background BOM generation.
- [x] Show normalized BOM and deterministic review findings from generated artifacts.
- [x] List, open, and regenerate supported BOM/review artifacts from the GUI.
- [x] Add a supplier view driven by plugin manifests, including safe credential labels and stored offer candidates.
- [x] Add board and assembly metric views backed by existing analysis engines.
- [x] List captured reply messages and inspect imported source-backed offer candidates.
- [x] Add saved landed-cost comparison, coverage gaps, verified run regeneration, and report artifact browsing.
- [x] Add project settings editing for board quantities while preserving other TOML configuration.
- [x] Add run progress, warning/error messages, and output-folder shortcuts.
- [x] Add automated headless GUI workflow smoke coverage for generated artifacts and quote-data loading.
- [x] Document GUI setup and launch.
- [x] Persist append-only accept/dismiss/defer review decisions with comments in a separate project artifact.
- [x] Edit and persist MPN overrides in the normalized BOM with a visible user source and under-constrained filter.
- [x] Show provenance badges for every editable BOM field (currently MPN only).
- [ ] Add approval-gated MPN and supplier part-number write-back to KiCad schematics.
- [x] Open cited review evidence files while confining paths to the selected project.
- [x] Generate and persist scalar supplier settings from manifests while preserving unknown plugin keys and excluding secrets.
- [x] Show keyring credential status and save secret fields directly to the OS keyring.
- [x] Add supplier-specific result and plugin documentation panes.
- [x] Show board-house and assembler declared limits against extracted board and assembly metrics.
- [x] Add supplier-specific board/assembly capability and offer-result panes.
- [x] Confirm, correct, or reject imported offer candidates in the GUI with append-only decisions and source references.
- [x] Open the project-stored quote file cited by a selected candidate.
- [ ] Highlight the cited row/cell or PDF span and review queued rows without extracted offers.
- [x] Add configurable price and lead-time comparison weights, persisted for reproducible runs.
- [x] Show coverage gaps, lead time, and landed-cost duty breakdown in comparisons.
- [x] Add best-mix analysis with line-level source references and supplier charges.
- [x] Add comparison charts grouped by board quantity and currency.
- [ ] Add editors for component, board, assembly, AI, email/signing, approval, and plugin settings.
- [ ] Add run-all, quote-only, stop, run queue, and AI cost status controls.
- [ ] Run interactive GUI acceptance checks on supported desktop platforms.

## Later milestones

- [ ] M9: KiCad launchers (IPC action and legacy SWIG fallback).
- [ ] M10: hardening and release checks.

## Recommended completion order

1. Collect independently reviewed real-world supplier samples to close M6's remaining validation item.
2. Finish M8's standalone GUI against stored data and existing offline pipeline stages.
3. Add M9 KiCad launchers, then finish M10 hardening and release checks.

M3–M5 are complete, and M4 provides durable analysis outputs. M6's real-world
validation needs representative sample files, so code-side work can continue while
those samples are collected.
