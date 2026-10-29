# KiProd desktop GUI

Install the optional desktop toolkit into the project environment:

```bash
./scripts/setup-gui.sh
./scripts/run.sh gui --project /path/to/kicad/project
```

Omit `--project` to open the window first and choose a project. The current M8
workflow discovers project inputs and variants, builds and saves the normalized
BOM and deterministic review, extracts board and assembly metrics where a board is
present, checks those metrics against declared supplier capability limits, and
refreshes the local supplier and quote views. Work runs in a background
thread; the run bar shows progress and the lower drawer records output paths and
warnings.

The Components view discovers project, user, and bundled plugin manifests in that
precedence order. It builds basic settings forms from manifest fields and saves
values under `quotes/config/plugin-settings/`, preserving unknown keys. Secret
fields are entered into the system keyring and only their configured/missing status
is shown. Credential values are never written to project files or logs. The GUI
does not call supplier adapters. Each selected supplier has Overview, Results, Docs,
and Settings tabs. Results lists matching offers already imported from local quote
files; Docs renders the plugin-local `README.md` when present. Neither pane invokes
the plugin or makes network requests. Quotes Inbox lists captured
`.eml` replies and locally saved quote-import JSON. Selecting an offer file shows
its parsed candidates and a separate review queue for source rows that were not
extracted. Double-clicking a queued row opens its source file when it is stored
inside the project. A candidate can be confirmed, corrected
from typed offer JSON, or rejected; corrections must preserve its original source
reference, and correction/rejection requires a comment. Decisions are append-only
in `quotes/review.decisions.json`. The cited source file can be opened when it is
stored under the project production folder. These views do not poll mailboxes or
send messages. Headless smoke
tests cover the data-loading and artifact-writing workflow without requiring PySide6.

The current GUI provides an editable MPN column with a source label and a filter for
lines missing MPNs or footprints. MPN overrides are saved in
`bom.user-overrides.json` and applied again when the GUI opens the project. It also
provides read-only board/assembly/supplier/quote views and a review view with
append-only accept/dismiss/defer decisions and comments. Saved landed-cost
comparison and report regeneration are available; regeneration checks saved input
hashes first. The project settings editor changes board quantities while preserving
unrelated TOML keys. Review decisions are stored separately in
`review.decisions.json`.

M8 still includes provenance badges for all BOM fields and approved schematic write-back, direct
review source navigation, editable manifest-generated supplier settings, in-GUI quote
confirmation, richer weighted comparison, broader settings editors, run controls,
and interactive desktop acceptance checks. These require PySide6 and a desktop
session; the current automated checks exercise the data and artifact layer headlessly.
