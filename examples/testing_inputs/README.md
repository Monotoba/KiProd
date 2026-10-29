# Synthetic testing inputs

These files use fictional quote data and contain no real supplier, customer, or
project information. They are for local manual and automated testing only.

- `quote_example.csv`: supplier-style header aliases with an introductory title and quote number.
- `quote_example.xlsx`: equivalent table in an XLSX workbook, with metadata above the header.
- `quote_example.pdf`: labeled-field quote PDF; extraction is intentionally low confidence and requires human review.
- `privacy_clean_board.kicad_pcb`: clean board fixture for privacy preflight.
- `privacy_flagged_visibility.kicad_prl`: saved KiCad layer visibility state designed to trigger the privacy check.

Set up the project, then parse a quote:

```bash
./scripts/setup.sh
./scripts/run.sh rfq parse-quote examples/testing_inputs/quote_example.csv \
  --supplier-id example-supplier --output /tmp/kiprod-example-offers.json
./scripts/run.sh rfq parse-quote examples/testing_inputs/quote_example.xlsx \
  --supplier-id example-supplier --output /tmp/kiprod-example-xlsx-offers.json
./scripts/run.sh rfq parse-quote examples/testing_inputs/quote_example.pdf \
  --supplier-id example-supplier --output /tmp/kiprod-example-pdf-offers.json
```

Run the privacy preflight on the clean and intentionally flagged examples:

```bash
./scripts/run.sh rfq scan-privacy examples/testing_inputs/privacy_clean_board.kicad_pcb
./scripts/run.sh rfq scan-privacy examples/testing_inputs/privacy_flagged_visibility.kicad_prl
```

The last command should report hidden KiCad layer visibility and exit with status 3.
