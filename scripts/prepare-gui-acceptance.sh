#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="${project_root}/.venv/bin/python"
if [[ ! -x "${python_path}" ]]; then
  echo "Run ./scripts/setup.sh first to create the project environment." >&2
  exit 2
fi

acceptance_root="$(mktemp -d "${TMPDIR:-/tmp}/kiprod-gui-acceptance.XXXXXX")"
acceptance_project="${acceptance_root}/basic"
quote_dir="${acceptance_project}/docs/production/quotes/imports"
mkdir -p "${acceptance_project}" "${quote_dir}"
cp -a "${project_root}/tests/projects/basic/." "${acceptance_project}/"
cp "${project_root}/tests/fixtures/rfq_quote.csv" "${quote_dir}/sample.csv"

"${python_path}" -m kiprod rfq parse-quote "${quote_dir}/sample.csv" \
  --supplier-id com.kiprod.supplier.fixture \
  --output "${quote_dir}/sample.quote.json"

cat <<EOF
Disposable GUI acceptance project: ${acceptance_project}

Run All:
  ./scripts/run.sh gui --project "${acceptance_project}" --mode all

Quote-only:
  ./scripts/run.sh gui --project "${acceptance_project}" --mode quote-only

The project is under a temporary directory and can be removed when finished:
  rm -r "${acceptance_root}"
EOF
