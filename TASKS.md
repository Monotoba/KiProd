# KiProd task list

## M1 — Ingest, export, and BOM CLI (in progress)

- [x] Create isolated Git repository, project metadata, local developer scripts, and test fixture.
- [x] Discover a KiCad project and hash its relevant source files.
- [x] Read KiCad schematic S-expressions without importing KiCad.
- [x] Build a deterministic normalized BOM, honoring `in_bom` / DNP markers.
- [x] Write JSON and CSV artifacts with provenance; test source and generated-BOM paths.
- [ ] Add `kicad-cli` export adapter and golden fixtures from real KiCad 10 projects.
- [ ] Detect variants and reconcile imported BOM CSVs with schematic data.

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
