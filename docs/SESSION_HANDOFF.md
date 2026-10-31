# Session handoff

Updated 2026-10-31. Use this note to resume the KiProd launcher acceptance
work after restarting the computer.

## Repository checkpoint

- Repository: `/home/randy/projects/KiCAD-Plugins/KiProd`
- Branch: `main`
- Latest pushed commit: `08546e7` (`Save launcher acceptance session handoff`)
- The only untracked repository item observed was
  `C:\Users\User\Desktop\kleplace.log`. It is unrelated and must be left
  untouched.

The disposable launcher fixture is in `tests/projects/launcher_acceptance/`.
It contains a PCB, an empty root schematic, and a KiCad project file. Generate
a fresh temporary copy after reboot with:

```bash
./scripts/prepare-kicad-launcher-acceptance.sh
```

The script prints the board path and baseline SHA-256. Use the exact printed
project and board paths; do not use a production design for launcher checks.

## What has been verified

- KiCad 10.0.8 is installed locally (`kicad-cli version`). KiCad 10.0.7 SWIG
  menu visibility and launch were previously confirmed by the user.
- The KiCad 10.0.8 PCB Editor IPC add-on was previously observed registering all
  three actions from the disposable board.
- The user-provided 2026-10-30 screenshot shows KiProd opened on the disposable
  project. The workspace reported one schematic, one board, and three hashed
  inputs. The log shows a quote-only refresh completed with zero captured/imported
  quotes, then Run All wrote a BOM and reviewed three lines with four
  deterministic findings.
- The fixture board passes KiCad 10.0.8 DRC with zero violations. The empty
  schematic parses with `kicad-cli sch export svg` and satisfies KiProd project
  discovery.

## Current acceptance gap

The screenshot does not identify whether the user invoked the IPC menu actions
or the already-verified SWIG action and then used the KiProd GUI controls. Also,
the board hash shown in the screenshot is
`b57feb51905abd1a8776d69bd64db0935213a34d092a811405edcca5a228e34f`, while the
committed fixture baseline is
`959ffcd4d6aca17affe31207b43c947e6016ae73ba25c8c10a234534e32e3357`.
The temporary PCB and schematic changed during the interactive session. The PCB
was converted to KiCad 10's newer file-format marker and gained drawing/track
objects; the schematic also gained content. The cause is unknown, so do not
attribute these edits to KiProd or overwrite/delete the changed temporary copy.

For a clean acceptance run after reboot:

1. Generate a fresh temporary project with the script above.
2. Open its board in the PCB Editor.
3. Invoke **Run KiProd production workflow** and **Refresh KiProd quote data**
   from the PCB Editor's registered IPC actions (toolbar or plugin-action UI),
   and note the mode each opens. **Tools → External Plugins → Open KiProd** is
   the separate legacy SWIG fallback, not an IPC action.
4. Compare the board's final SHA-256 with the script's printed baseline. If it
   changes, preserve that temporary project and record the difference; do not
   count the read-only board-integrity check as passed.

Do not investigate the intermittent toolbar overflow dropdown yet. The user
asked to defer that investigation until KiProd is working and complete.

## Preserved 2026-10-31 fixture run

The user opened the tracked source fixture at
`tests/projects/launcher_acceptance/` rather than a disposable temporary copy.
Their screenshot shows the KiProd workspace completing **Run All** against that
project: three BOM lines, four deterministic findings, and generated BOM output.
It does not identify whether an IPC action or the SWIG fallback launched the
workspace, so it is supporting workflow evidence only and does not close an M9
acceptance task.

KiCad and the run materially changed that tracked fixture. Preserve all of these
items for investigation; do not reset, overwrite, or delete them without the
user's explicit instruction:

- Modified `launcher_acceptance.kicad_pcb`, `.kicad_sch`, and `.kicad_pro`.
- The `.history/` directory, generated `docs/production/bom/` artifacts, and
  KiCad lock files.
- The copied `C:\\Users\\User\\Desktop\\kleplace.log` item.

The post-run PCB SHA-256 is
`3a16ada02ae1c5e4319e9c87efa57b36efe1e5352536b7afe823a74c457c5b11`,
which differs from the clean committed baseline
`959ffcd4d6aca17affe31207b43c947e6016ae73ba25c8c10a234534e32e3357`.
Do not attribute the changes to KiProd without further isolation. Future clean
acceptance must use a newly generated temporary copy.

## Clean temporary run, IPC controls unavailable (2026-10-31)

The user reopened the temporary project at
`/tmp/kiprod-kicad-acceptance.hgsR9j/launcher_acceptance/` and opened KiProd
through the only accessible launcher UI, **Tools → External Plugins**. That is
the SWIG fallback. They then ran the GUI's Run All workflow manually. The GUI
completed successfully and wrote its expected local artifacts; the temporary
PCB remained at the exact clean baseline hash
`959ffcd4d6aca17affe31207b43c947e6016ae73ba25c8c10a234534e32e3357`.

The KiCad 10 IPC toolbar controls, including **Refresh KiProd quote data**, were
not accessible to the user; only the External Plugins menu was available. Do
not ask the user to repeat this path as IPC acceptance. This is confirming
evidence for the already-accepted KiCad 10 SWIG fallback and evidence for the
open toolbar/IPC-control availability follow-up, but it does not close the IPC
action-invocation task.

## Remaining milestones

- M9: IPC action invocation on KiCad 9 and 10; SWIG launcher on KiCad 8. KiCad
  10 IPC invocation and board-hash integrity still need unambiguous acceptance.
- M9 follow-up: diagnose the intermittent plugin-toolbar overflow dropdown,
  deferred as noted above.
- M10: exercise the tagged release workflow after a versioned release is
  approved.

See `TASKS.md` and `docs/KICAD_LAUNCHERS.md` for the maintained milestone list
and launcher procedure.
