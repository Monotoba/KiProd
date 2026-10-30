# KiCad launchers

KiProd provides PCB Editor launchers for KiCad 8–11. Each launcher passes project
paths and a requested GUI mode to the standalone KiProd process. KiProd then reads
the project from disk through the same pipeline used by its CLI.

## Install

Set up the development environment and optional GUI dependency, then run the
installer from that environment:

```bash
./scripts/setup.sh
./scripts/setup-gui.sh
./.venv/bin/python scripts/install_kicad_launchers.py --kicad-version 10.0
```

On Windows, run the installer with the interpreter in `.venv\Scripts\python.exe`.
The installer stores the selected interpreter and project source path in the
user-level `kiprod/launcher.json` configuration file. The BOM Generator hook is
copied under that KiCad version's data directory. For KiCad 9 and 10, the IPC
manifest and SWIG action are staged together under the versioned
`3rdparty/plugins/com_github_monotoba_kiprod` directory used by KiCad's add-on
manager. On Linux, the installer uses KiCad's lowercase `kicad` data directory,
matching the path reported by KiCad 10.0.7. KiCad 8 uses its legacy scripting
plugin directory. The installer prints the exact command to add to the Schematic
Editor BOM Generator. Pass `--documents-home PATH` to override the KiCad data
directory used by the launchers and BOM hook.
`KICAD_DOCUMENTS_HOME` is used when present.

Build a Plugin and Content Manager package with:

```bash
./.venv/bin/python scripts/package_kicad_addon.py
```

In KiCad, open **Tools → Plugin and Content Manager → Install from File** and
select `dist/kiprod-kicad-addon.zip`, then apply the pending change and restart
the PCB Editor. This records KiProd in the manager's Installed list. The package
supports KiCad 9 and 10 and includes both IPC and legacy SWIG launchers.

Restart KiCad after installing. In KiCad 9 and newer, enable the IPC API in
**Preferences → Plugins**. KiCad's Python plugin environment installs the pinned
`kicad-python` dependency from the IPC launcher's `requirements.txt` on first use;
this can delay the actions appearing in the PCB Editor. The installer also adds
the legacy SWIG action for KiCad 8–10. KiCad 11 removed that legacy API and uses
the IPC launcher.

## PCB Editor actions

The IPC plugin registers three actions: **Run KiProd production workflow**,
**Refresh KiProd quote data**, and **Open KiProd**. They read the open board's
project directory from KiCad's IPC API, then start the configured KiProd Python
environment in a separate process. The run and quote actions select the
corresponding GUI mode; the open action starts the workspace without starting a
run. IPC actions are available in the PCB Editor's plugin preferences and as
toolbar buttons; they are not entries in the legacy **Tools → External Plugins**
menu. All three IPC actions request a toolbar button by default. KiCad lets users
customize plugin toolbar buttons in the PCB Editor preferences. The toolbar may
provide a down-arrow overflow list for plugin actions that do not fit. A user
reported that this dropdown intermittently disappears with a large set of
plugins. Keep **Tools → External Plugins** as a fallback, and use the Action
Plugins preferences to prioritize frequently used SWIG buttons.
The legacy SWIG fallback offers **Open KiProd** from **Tools → External Plugins**
and only reads the current saved board path before launching the same standalone
GUI.

The launchers do not edit the board. Analysis and artifact generation remain in
the standalone application. The launchers remove credential-like environment
variables before starting KiProd, while preserving KiCad's IPC socket/token and
desktop variables. The current GUI run modes do not make AI requests or send
supplier email.

## Schematic Editor BOM Generator

Add the command printed by the installer in **Tools → Generate BOM**. KiCad
substitutes `%I` with the generated netlist XML path and `%O` with the output path
base. The hook derives the project directory from `%I`, runs
`kiprod run --project PROJECT --non-interactive`, and copies the normalized
`docs/production/bom/bom.csv` to KiCad's requested output CSV path. It reports a
failure instead of exporting a partial BOM when the normal KiProd run cannot
complete. The netlist is used to find the project directory; the pipeline reads
saved schematic and project files, so unsaved editor changes are not included.

## Acceptance record

The installer and BOM Generator hook were exercised with KiCad CLI 10.0.7 using
the `tests/projects/basic` fixture. KiCad generated the XML netlist, the hook
completed the KiProd run, and its CSV output matched the normal CLI-generated BOM
byte-for-byte. The PCB Editor IPC menu actions and legacy SWIG menu action still
need interactive invocation in their supported KiCad versions.

On 2026-10-30, KiCad PCB Editor 10.0.7 scanned the installed IPC plugin on the
disposable board with its API server enabled. Its trace accepted the reverse-DNS
identifier `com.github.monotoba.kiprod`, registered all three actions, and
created the plugin Python environment. This confirms IPC plugin discovery and
action registration in KiCad 10.0.7; invoking the actions from the editor menus
and verifying the resulting standalone GUI context remains open.

On 2026-10-30, the user confirmed that **Open KiProd** appeared under **Tools →
External Plugins** in KiCad 10.0.7 and opened the KiProd workspace. This verifies
the SWIG launcher and project handoff for KiCad 10.0.7. IPC action invocation and
the KiCad 8 SWIG check remain open.

The same KiCad 10.0.7 setup has 73 enabled SWIG actions and 25 enabled IPC
actions. The user reports that KiCad's scrollable toolbar overflow dropdown
sometimes disappears when many plugins are installed, including after adding a
plugin. KiProd's SWIG and IPC actions were moved to the beginning of their saved
orders and given explicit icons, but the intermittent dropdown behavior has not
been reproduced or attributed to a specific plugin. Keep root-cause isolation as
an open compatibility task; use **Tools → External Plugins → Open KiProd** as
the confirmed fallback.

## PCB Editor acceptance procedure

Create a disposable project with a saved board:

```bash
./scripts/prepare-kicad-launcher-acceptance.sh
```

The script prints the project path and baseline board hash. If the launchers are
not installed for the KiCad version under test, install them from the KiProd
environment as described above, then restart KiCad. Open the printed
`launcher_acceptance.kicad_pcb` in the PCB Editor. This visual smoke-test board
uses standard footprints and has no electrical nets; it is not a manufacturing
design. Its source files are in `tests/projects/launcher_acceptance/`.

For KiCad 9 or 10 IPC acceptance:

1. Enable the IPC API under **Preferences → Plugins**, restart KiCad if prompted,
   and wait for the IPC plugin dependency setup to finish.
2. In the PCB Editor preferences, confirm **KiProd** and its three actions are
   listed. Confirm the toolbar buttons are enabled. When the toolbar is crowded,
   check whether KiCad displays its plugin overflow dropdown.
3. Run **Open KiProd** and confirm the standalone workspace opens on the
   disposable project. Then exercise the Run and Quote actions and confirm each
   selects the matching GUI mode.

For KiCad 8 or 10 SWIG acceptance, use **Tools → External Plugins → Open KiProd**
and confirm the standalone workspace opens on the same disposable project. If
the menu entry is missing, open KiCad's scripting console and run
`import pcbnew; print(pcbnew.PLUGIN_DIRECTORIES_SEARCH)`. Confirm
`__init__.py` and `kiprod_launcher.py` are in a reported directory, then restart
KiCad.

After each path, compare the board's SHA-256 with the baseline printed by the
script; launcher actions should leave the board unchanged. Record the exact KiCad
version, API-server setting, action visibility, project context, result of each
action, and post-run hash. Run the version-specific procedure on every supported
version named in the acceptance task; one version does not stand in for another.

## Limits

- KiCad 9 and 10 IPC plugins require the PCB Editor and an open, saved board.
- KiCad 8 can use the SWIG fallback; KiCad 11 uses IPC and does not load the SWIG
  plugin.
- KiCad 9/10 IPC provides project context only; BOM export and other processing
  still use KiProd's offline code and `kicad-cli` where required.
- The IPC actions and BOM Generator use the Python interpreter configured by the
  installer. Re-run the installer after moving the KiProd checkout or virtual
  environment.

KiCad's [IPC add-on documentation](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)
and [PCB Python binding documentation](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)
describe the primary API and the deprecated fallback.
