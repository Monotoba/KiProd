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

The GUI uses Qt 6's device-pixel scaling and system fonts. Its initial window size
is chosen from the screen's available logical geometry, capped at 1180 × 760 logical
pixels and honoring the layout's minimum size when the screen allows. Layouts resize
with the window; KiProd does not apply an additional manual scale factor.

Run All builds BOM/review and board outputs. Quote-only refresh reads local captured
replies and imported offers without regenerating BOM artifacts. Stop is cooperative:
it is enabled during discovery and analysis, and stops at a safe checkpoint before
writing outputs. Queued jobs run sequentially and show queued/running/completed/stopped
or failed status. The usage indicator reports $0.00 because these GUI run modes do
not make AI requests.

The Components view discovers project, user, and bundled plugin manifests in that
precedence order. It builds basic settings forms from manifest fields and saves
values under `quotes/config/plugin-settings/`, preserving unknown keys. Secret
fields are entered into the system keyring and only their configured/missing status
is shown. Credential values are never written to project files or logs. The GUI
does not call supplier adapters. Each selected supplier has Overview, Results, Docs,
and Settings tabs. Results lists matching offers already imported from local quote
files; Docs renders the plugin-local `README.md` when present. Neither pane invokes
the plugin or makes network requests. Board Fab and Assembly tabs show each
supplier's declared manifest limits beside project metrics and compatibility
findings. Quotes Inbox lists captured
`.eml` replies and locally saved quote-import JSON. Selecting an offer file shows
its parsed candidates and a separate review queue for source rows that were not
extracted. Double-clicking a queued row opens its source file when it is stored
inside the project. Selecting a candidate or queued row opens an in-app evidence
preview, highlighting the cited CSV/XLSX row or extracted PDF block. A candidate can be confirmed, corrected
from typed offer JSON, or rejected; corrections must preserve its original source
reference, and correction/rejection requires a comment. Decisions are append-only
in `quotes/review.decisions.json`. The cited source file can be opened when it is
stored under the project production folder. These views do not poll mailboxes or
send messages. Headless smoke
tests cover the data-loading and artifact-writing workflow without requiring PySide6.

The comparison table and saved Markdown report include parts, shipping, NRE, duty,
and fees beside the landed total and per-board amount. Ranking uses normalized price
and lead-time weights within matching quantity and currency groups. The controls
accept non-negative weights (price defaults to 1, lead time to 0); each run archives
its weights so regeneration preserves the ranking. Lead time contributes only when
at least one complete lead-time value is available for the comparison group.
The Best mix tab selects the lowest extended-price source per required MPN within
each quantity and currency group, then applies the selected source's supplier-level
shipping, NRE, duty, and fees once per selected supplier. Each line retains its
quote source reference, and uncovered MPNs remain visible as gaps.
The Charts tab shows landed cost per board and weighted score bars, grouped by
quantity and currency so incomparable groups are not plotted together.
After generating a best mix, the Compare view can preview MPN and Supplier Part
Number changes for matching schematic components. Applying changes requires an
explicit confirmation, keeps a unique `.kiprod.bak` copy of each modified schematic,
and aborts if a source schematic changed after the preview.

The current GUI provides an editable MPN column with a source label and a filter for
lines missing MPNs or footprints. MPN overrides are saved in
`bom.user-overrides.json` and applied again when the GUI opens the project. It also
provides read-only board/assembly/supplier/quote views and a review view with
append-only accept/dismiss/defer decisions and comments. Saved landed-cost
comparison and report regeneration are available; regeneration checks saved input
hashes first. Settings include a focused board-quantity editor and a validated project
TOML editor for paths and component rules. The TOML editor preserves entered comments
and unknown keys, and rejects secret-like keys so credentials stay in the OS keyring.
Review decisions are stored separately in `review.decisions.json`.

M8 still includes run-all/quote-only/stop/queue controls, dedicated editors for
assembly, AI, email/signing, and approval settings that do not yet have project config
schemas, and interactive desktop acceptance checks. Automated checks exercise the
data and artifact layer headlessly.
