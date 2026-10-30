#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
acceptance_root="$(mktemp -d "${TMPDIR:-/tmp}/kiprod-kicad-acceptance.XXXXXX")"
acceptance_project="${acceptance_root}/launcher_acceptance"
mkdir -p "${acceptance_project}"
cp -a "${project_root}/tests/projects/launcher_acceptance/." "${acceptance_project}/"

printf 'Disposable KiCad launcher project: %s\n' "${acceptance_project}"
printf 'PCB board file: %s\n' "${acceptance_project}/launcher_acceptance.kicad_pcb"
printf 'Baseline board SHA-256: '
sha256sum "${acceptance_project}/launcher_acceptance.kicad_pcb"
printf '\nOpen the board in KiCad PCB Editor and follow docs/KICAD_LAUNCHERS.md.\n'
printf 'Remove the disposable project when finished: rm -r %q\n' "${acceptance_root}"
