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
- [ ] Add manifest schema file, subprocess isolation, and recorded supplier adapter fixtures.

## Later milestones (blocked on prior acceptance)

- [ ] M4: traceable analysis and reports.
- [ ] M5: board/assembly extraction and RFQs.
- [ ] M6: signed email RFQs and inbox.
- [ ] M7: typed AI/review layer.
- [ ] M8–M10: GUI, KiCad launchers, and hardening.
