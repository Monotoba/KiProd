#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch_dir="$(mktemp -d)"
trap 'rm -rf "${scratch_dir}"' EXIT

python3 -m venv "${scratch_dir}/build-venv"
build_python="${scratch_dir}/build-venv/bin/python"
"${build_python}" -m pip install --upgrade build
"${build_python}" -m build --outdir "${scratch_dir}/dist" "${project_root}"

python3 -m venv "${scratch_dir}/venv"
python_path="${scratch_dir}/venv/bin/python"
"${python_path}" -m pip install "${scratch_dir}"/dist/*.whl

cd "${scratch_dir}"
"${scratch_dir}/venv/bin/kiprod" --help >/dev/null
"${scratch_dir}/venv/bin/kiprod" bom \
  --project "${project_root}/tests/projects/basic" \
  --output-dir "${scratch_dir}/output"
test -s "${scratch_dir}/output/bom.normalized.json"
test -s "${scratch_dir}/output/bom.csv"
supplier_profiles="$("${scratch_dir}/venv/bin/kiprod" plugins list \
  --project "${project_root}/tests/projects/basic" | grep -c 'Profile only$')"
test "${supplier_profiles}" -eq 28

echo "Built wheel and source archive; installed wheel, generated a BOM, and found all supplier profiles."
