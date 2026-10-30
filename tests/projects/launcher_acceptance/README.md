# KiProd launcher acceptance board

This is a small, disposable KiCad PCB project for exercising KiProd's PCB Editor
launchers. It contains a board outline, two 1x4 headers, a 0603 resistor, and a
signal test point. The layout is a visual smoke-test fixture only: it has no
electrical nets and is not intended for fabrication.

The footprints come from KiCad's standard `Connector_PinHeader_2.54mm`,
`Resistor_SMD`, and `TestPoint` libraries. The board file uses the KiCad 8+
`20240108` PCB format so it can be opened by the supported KiCad 8, 9, and 10
launchers.

Create a temporary copy with:

```bash
./scripts/prepare-kicad-launcher-acceptance.sh
```

The script prints the temporary project path and baseline board SHA-256. Use the
printed path in the PCB Editor, then remove only that temporary directory after
acceptance.
