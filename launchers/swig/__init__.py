from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcbnew  # noqa: E402
from kiprod_launcher import launch_gui  # noqa: E402


class KiProdActionPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "Open KiProd"
        self.category = "Production"
        self.description = "Open the KiProd production workspace for this project."
        self.show_toolbar_button = True

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None:
                raise RuntimeError("open a saved PCB in KiCad before launching KiProd")
            board_path = board.GetFileName()
            if not board_path:
                raise RuntimeError("save the current PCB before launching KiProd")
            launch_gui(board_path, "open")
        except Exception as exc:
            print(f"KiProd SWIG launcher: {type(exc).__name__}: {exc}", file=sys.stderr)


KiProdActionPlugin().register()
