# Real supplier quote validation

M6's remaining acceptance item is to evaluate quote extraction on independently
reviewed supplier documents. The checked-in quote fixtures are synthetic and do
not satisfy this requirement.

## Samples to provide

Provide real supplier-issued quote files in the formats you use, ideally CSV,
XLSX, and PDF, with at least two different suppliers represented. Include
ordinary line items, multiple price breaks where available, and examples of any
supplier-specific column headings or preamble rows that have caused issues.
Do not include purchase orders, account credentials, payment details, shipping
addresses, or unrelated customer information. If you redact a file, preserve its
table structure and all fields needed to validate parsing. Keep an unmodified
original available locally so the redaction does not alter the expected values.

For every file, independently check each extracted line against the original
document and prepare expected rows containing:

- `mpn`: manufacturer part number
- `spn`: supplier part number
- `quantity`: minimum quantity for the price break
- `unit_price`: quoted unit price
- `currency`: ISO currency code
- `review_required`: whether the parser must put the result in the human-review queue

The reviewer should also record supplier, quote date, source page/sheet/row, and
any omitted or ambiguous rows. Do not use an LLM-generated annotation as the
ground truth.

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
