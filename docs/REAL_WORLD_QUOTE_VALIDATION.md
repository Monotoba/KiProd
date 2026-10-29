# Real supplier quote validation

## Completed sample evaluation

The project owner confirmed that they reviewed the supplied DigiKey and Mouser
quotes. Evaluation used private files under `examples/real-data/`; this directory
is ignored by Git. Neither the quote files nor their expected labels or report
are published.

The Mouser workbook contained 18 complete quoted rows, two incomplete price
rows, and one unmatched row. For this local evaluation, its OOXML worksheet was
reconstructed to a temporary CSV because `openpyxl` was unavailable in the
development environment. The expected fields were mapped from the corresponding
supplier columns and reviewed by the project owner. The parser extracted all 18
rows exactly and sent the three incomplete rows to human review. Field accuracy,
exact-row precision, and recall were each 100%.

The DigiKey file contained 21 unmatched, unquoted rows. The parser produced no
offers and sent all 21 rows to human review, as expected. The overall evaluation
passed the 95% threshold with no skipped cases. The DigiKey sample was parsed
directly; the Mouser sample evaluation exercised the shared table parser using
the reconstructed CSV, not the original workbook's `openpyxl` loading path. The
XLSX path remains covered by synthetic fixture tests.

The reproducible evaluation command and expected JSON schema are described
below. The private sample report is intentionally not stored in the repository.

## Additional samples

The M6 sample acceptance is complete. Further validation can add supplier-issued
files in other formats, especially XLSX loaded directly and PDF, or quotes with
multiple price breaks and additional supplier-specific headers. Do not include
purchase orders, account credentials, payment details, shipping addresses, or
unrelated customer information. If you redact a file, preserve its table
structure and all fields needed to validate parsing. Keep an unmodified original
available locally so the redaction does not alter the expected values.

For every file, independently check each extracted line against the original
document and prepare expected rows containing:

- `mpn`: manufacturer part number
- `spn`: supplier part number
- `quantity`: minimum quantity for the price break
- `unit_price`: quoted unit price
- `currency`: ISO currency code
- `review_required`: whether the parser must put the result in the human-review queue

For future samples, record supplier, quote date, source page/sheet/row, and any
omitted or ambiguous rows. Do not use an LLM-generated annotation as the ground
truth.

## Run the evaluation

Copy the approved sample files into a private validation directory and create an
expected JSON file in the schema used by
[`tests/fixtures/rfq_quote_expected.json`](../tests/fixtures/rfq_quote_expected.json).
Then run:

```bash
.venv/bin/python -m kiprod.rfq.quote_eval \
  --fixture-dir /path/to/private/samples \
  --expected /path/to/private/expected.json \
  --minimum-accuracy 0.95 \
  --output /path/to/private/report.json
```

Review field accuracy, exact-row precision and recall, parser review-policy
behavior, and every error or skip. M6's item can be checked off only after the
independent labels are complete and the 95% field-accuracy threshold passes.
Keep supplier documents and labels out of Git unless they are explicitly
approved for public redistribution; a private evaluation report can record the
result without publishing the source quotes.
