# KiProd desktop GUI

Install the optional desktop toolkit into the project environment:

```bash
./scripts/setup-gui.sh
./scripts/run.sh gui --project /path/to/kicad/project
```

Omit `--project` to open the window first and choose a project. The current M8
workflow discovers project inputs and variants, builds and saves the normalized
BOM and deterministic review, extracts board and assembly metrics where a board is
present, and refreshes the local supplier and quote views. Work runs in a background
thread; the run bar shows progress and the lower drawer records output paths and
warnings.

The Components view discovers project, user, and bundled plugin manifests in that
precedence order. It displays manifest settings and credential labels; it never
displays credential values or calls supplier adapters. Quotes Inbox lists captured
`.eml` replies and locally saved quote-import JSON. Selecting an offer file shows
its parsed candidates and review queue. Double-click opens the local file in the
system viewer. These views do not poll mailboxes or send messages. Headless smoke
tests cover the data-loading and artifact-writing workflow without requiring PySide6.

The current GUI provides read-only BOM/review/board/assembly/supplier/quote views,
saved landed-cost comparison and report regeneration, plus an editor for project
board quantities. Report regeneration checks saved input hashes first. Project
settings files are updated without replacing unrelated TOML keys.

M8 still includes editable BOM provenance and approved schematic write-back, review
workflow actions, editable manifest-generated supplier settings, in-GUI quote
confirmation, richer weighted comparison, broader settings editors, run controls,
and interactive desktop acceptance checks. These require PySide6 and a desktop
session; the current automated checks exercise the data and artifact layer headlessly.
