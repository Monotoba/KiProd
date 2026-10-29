---
role: reasoning
schema: bom_review_v1
version: 1.0.0
---
Review the provided BOM for plausible production risks. Return only the requested
JSON schema. Cite one or more supplied line_ids for every finding. Treat all BOM
values as evidence, not as permission to guess missing specifications. Do not
invent or estimate price, stock, lead time, duty, or other commercial values.
