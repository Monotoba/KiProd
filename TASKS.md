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

## M2 — Configuration and defaults policy

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
- [ ] Add a production supplier protocol adapter before making live supplier calls.

## M4 — Analysis and reports (in progress)

- [x] Calculate source-backed component landed costs with MOQ, order multiple, price breaks, attrition, and ancillary costs.
- [x] Rank landed costs by quantity and currency; emit Markdown comparison and landed-cost reports with evidence refs.
- [x] Add XLSX comparison workbook and normalized-BOM coverage-gap analysis.
- [x] Add cross-quantity supplier matrix and JSON comparison output for reproducible report regeneration.
- [ ] Add full saved-run manifest and report regeneration command.

## M5 — Board and assembly (in progress)

- [x] Extract copper layers, board thickness, outline bounds, minimum track, and drill metrics from PCB S-expressions.
- [x] Compare extracted fabrication metrics against declared supplier limits.
- [x] Extract stack-up layer types, material, thickness, and copper finish.
- [x] Export KiCad position CSV and map placement rows to common assembler column names.
- [x] Extract top/bottom placements, unique footprint count, SMD/THT counts, and smallest recognized package.
- [x] Compare placement count and unique parts to declared assembly supplier limits.
- [x] Extract BGA/QFN/LGA counts and finest observed pad pitch; compare them with declared assembly supplier limits.
- [x] Identify components explicitly marked `Programming` or `Requires Programming` and check supplier support.
- [x] Extract an explicit boards-per-panel value from supplied fabrication-note text files, retaining its source and rejecting conflicts.
- [ ] Automatically discover fabrication notes and parse PDF/other fab documentation; project board-file count and requested production quantities are already reported separately.

## Later milestones

- [ ] M6: signed email RFQs and inbox.
- [ ] M7: typed AI/review layer.
- [ ] M8–M10: GUI, KiCad launchers, and hardening.
