# RFQ privacy scan validation

On 2026-10-29, `kiprod rfq scan-privacy` was run against the KiCad-installed
template projects under `/usr/share/kicad/template`:

- Arduino Uno
- BeagleBone-Black-Cape
- STM32 Nucleo-64 Morpho
- Arduino Mega

For each project, the `.kicad_pro`, `.kicad_sch`, and `.kicad_pcb` files were
scanned. The result was **0 findings across 12 files** (0% observed false-positive
rate on these clean samples). The source project files were not copied into this
repository.

This checks false positives for those clean examples. It does not measure detection
recall on projects that contain hidden layers or embedded personal metadata, and
the files are KiCad templates rather than independently reviewed supplier quote
samples. The latter remains an M6 validation item.
