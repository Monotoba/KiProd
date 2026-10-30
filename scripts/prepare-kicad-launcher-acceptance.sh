#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
acceptance_root="$(mktemp -d "${TMPDIR:-/tmp}/kiprod-kicad-acceptance.XXXXXX")"
acceptance_project="${acceptance_root}/basic"
mkdir -p "${acceptance_project}"
cp -a "${project_root}/tests/projects/basic/." "${acceptance_project}/"
cp "${project_root}/tests/fixtures/board_minimal.kicad_pcb" \
  "${acceptance_project}/basic.kicad_pcb"

printf 'Disposable KiCad launcher project: %s\n' "${acceptance_project}"
printf 'PCB board file: %s\n' "${acceptance_project}/basic.kicad_pcb"
printf 'Baseline board SHA-256: '
sha256sum "${acceptance_project}/basic.kicad_pcb"
printf '\nOpen the board in KiCad PCB Editor and follow docs/KICAD_LAUNCHERS.md.\n'
printf 'Remove the disposable project when finished: rm -r %q\n' "${acceptance_root}"
