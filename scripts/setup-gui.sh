#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_path="${project_root}/.venv"
if [[ ! -x "${venv_path}/bin/python" ]]; then
  echo "Run ./scripts/setup.sh first to create the project environment." >&2
  exit 2
fi
"${venv_path}/bin/python" -m pip install -e "${project_root}[gui]"
echo "Desktop GUI ready. Launch it with: ./scripts/run.sh gui"
