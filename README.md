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

## Development

`TASKS.md` is the maintained implementation plan. The detailed product
specification is retained in `docs/`. See `AGENTS.md` for non-negotiable
architecture and safety constraints.
