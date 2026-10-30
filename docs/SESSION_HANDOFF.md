# Session handoff

Updated 2026-10-30. Use this note to resume the KiProd launcher acceptance
work after restarting the computer.

## Repository checkpoint

- Repository: `/home/randy/projects/KiCAD-Plugins/KiProd`
- Branch: `main`
- Latest pushed commit: `bf9fe3e` (`Add root schematic to launcher test project`)
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
   specifically from **Tools → External Plugins**. Record that these menu
   entries are the IPC actions, and note the mode each opens.
4. Compare the board's final SHA-256 with the script's printed baseline. If it
   changes, preserve that temporary project and record the difference; do not
   count the read-only board-integrity check as passed.

Do not investigate the intermittent toolbar overflow dropdown yet. The user
asked to defer that investigation until KiProd is working and complete.

## Remaining milestones

- M9: IPC action invocation on KiCad 9 and 10; SWIG launcher on KiCad 8. KiCad
  10 IPC invocation and board-hash integrity still need unambiguous acceptance.
- M9 follow-up: diagnose the intermittent plugin-toolbar overflow dropdown,
  deferred as noted above.
- M10: exercise the tagged release workflow after a versioned release is
  approved.

See `TASKS.md` and `docs/KICAD_LAUNCHERS.md` for the maintained milestone list
and launcher procedure.
