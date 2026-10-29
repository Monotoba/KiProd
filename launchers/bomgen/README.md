# KiCad Schematic Editor BOM hook

Run `scripts/setup.sh` and `scripts/setup-gui.sh`, then install the launchers from
the KiProd project environment:

```bash
./.venv/bin/python scripts/install_kicad_launchers.py --kicad-version 10.0
```

The installer prints the exact command for the BOM Generator settings. Add it in
Schematic Editor under **Tools → Generate BOM**. KiCad replaces `%I` with its
intermediate netlist XML path and `%O` with the output base path. The hook runs
`kiprod run --project <netlist-directory> --non-interactive`, then copies KiProd's
normalized `bom.csv` to the output path requested by KiCad. If KiProd reports
missing required data, the hook returns that error instead of exporting a partial
BOM.

The input XML supplies project location only. KiProd re-reads the saved project
files through its normal pipeline, so output is the same normalized BOM written by
the CLI; unsaved schematic edits are not included.
