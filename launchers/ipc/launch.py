from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiprod_launcher import launch_gui  # noqa: E402


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "open"
    try:
        from kipy import KiCad

        client = KiCad()
        board = client.get_board()
        if board is None:
            raise RuntimeError("open a saved PCB in KiCad before launching KiProd")
        project = board.get_project()
        project_path = getattr(project, "path", None)
        if not isinstance(project_path, str) or not project_path:
            raise RuntimeError("KiCad did not provide the open project's path")
        return launch_gui(project_path, mode)
    except Exception as exc:
        print(f"KiProd IPC launcher: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
