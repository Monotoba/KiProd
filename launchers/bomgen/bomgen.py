from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiprod_launcher import run_bom_generator  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: bomgen.py NETLIST.xml OUTPUT.csv", file=sys.stderr)
        return 2
    try:
        return run_bom_generator(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"KiProd BOM generator: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
