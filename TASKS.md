# KiProd task list

## M1 — Ingest, export, and BOM CLI (in progress)

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

- [ ] Layer built-in, user, project, and CLI TOML settings.
- [ ] Implement default / flag / error / guess / inherit / ignore with exit codes.
- [ ] Validate quantities, including add/remove and range shorthand.

## Later milestones (blocked on prior acceptance)

- [ ] M3: plugin host and recorded supplier adapters.
- [ ] M4: traceable analysis and reports.
- [ ] M5: board/assembly extraction and RFQs.
- [ ] M6: signed email RFQs and inbox.
- [ ] M7: typed AI/review layer.
- [ ] M8–M10: GUI, KiCad launchers, and hardening.
