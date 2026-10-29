# KiProd

KiProd creates a traceable production package from a KiCad project: a normalized
BOM, production review findings, supplier quotes, and comparison reports.

This repository currently implements milestone **M1**: offline project discovery
and normalized BOM generation. It deliberately has no network, supplier, LLM, or
KiCad embedded-Python dependency.

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

Project and supplier plugins live under
`docs/production/quotes/config/suppliers/`. Use `kiprod plugins list` to inspect
available plugins, `kiprod plugins test PLUGIN_ID` for an isolated health check,
and `kiprod quote MPN --plugin PLUGIN_ID` to query a catalog plugin.

## Development

`TASKS.md` is the maintained implementation plan. The detailed product
specification is retained in `docs/`. See `AGENTS.md` for non-negotiable
architecture and safety constraints.
