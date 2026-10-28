# KiProd implementation rules

- Use Python 3.11+ with complete type annotations; keep `kiprod.core` strict-mypy compatible.
- The core imports without KiCad installed. Only `kiprod.kicad` may invoke `kicad-cli`.
- Launchers carry paths/context only; business logic belongs in the core.
- An LLM must never originate price, stock, lead-time, or duty data.
- All network access must eventually go through `kiprod.net.HttpClient`.
- Pipeline stages must be idempotent and keyed by their input hash.
- Never transmit data externally without a matching approval of the exact payload hash.
- CI tests use fixtures only; never make live supplier or LLM calls.

Build milestones in the order documented in `TASKS.md`; do not begin a milestone
until the preceding milestone's acceptance tests pass.
