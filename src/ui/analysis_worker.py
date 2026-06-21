"""Qt bridge for the framework-agnostic analysis pipeline.

The orchestrator runs on a plain ``threading.Thread`` and reports progress
through callbacks.  This :class:`AnalysisWorker` (a :class:`QObject`) wraps
those callbacks so they become Qt signals that are safely marshalled back to
the GUI thread.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from ..core.config import AppConfig
from ..core.models import MatchMetadata
from ..orchestrator.pipeline import AnalysisPipeline


class AnalysisWorker(QObject):
    """Drives :class:`AnalysisPipeline` and re-emits results as Qt signals."""

    progress = pyqtSignal(float, str)
    event = pyqtSignal(str, dict)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.pipeline = AnalysisPipeline(config)
        self.match: Optional[MatchMetadata] = None

    def start(self, match: MatchMetadata) -> None:
        self.match = match
        self.pipeline.run_async(
            match,
            on_progress=lambda v, m: self.progress.emit(v, m),
            on_event=lambda kind, payload: self.event.emit(kind, payload),
            on_done=self._on_done,
            on_error=self._on_error,
        )

    def stop(self) -> None:
        self.pipeline.stop()

    def is_running(self) -> bool:
        return self.pipeline.is_running()

    def _on_done(self, match: MatchMetadata) -> None:
        self.finished.emit(match)

    def _on_error(self, match: MatchMetadata, message: str) -> None:
        self.failed.emit(message)
