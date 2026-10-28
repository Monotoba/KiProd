# Native fixture origin

`native_counter.kicad_pro` and `native_counter.kicad_sch` are an unmodified,
renamed copy of KiCad's installed `demos/simulation/up-down-counter` project,
as distributed with KiCad 10.0.7. They provide a real KiCad S-expression
fixture with embedded symbol definitions and symbol-instance metadata.

The fixture is intentionally limited to the project and schematic files; its
simulation-only auxiliary files are not needed to produce a BOM.
