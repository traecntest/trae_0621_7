"""Application entry point.

Run with: ``python main.py``
"""

from __future__ import annotations

import sys

from src.core.logger import configure_logging, get_logger
from src.ui.main_window import run

if __name__ == "__main__":
    configure_logging()
    log = get_logger("main")
    log.info("TacticalReplay 启动中...")
    sys.exit(run())
