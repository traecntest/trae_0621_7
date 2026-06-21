"""HTML report viewer.

Loads the generated HTML report either from disk (using QWebEngineView when
available) or falls back to a plain text + open-in-browser approach so the
widget never crashes on environments without the webengine module.
"""

from __future__ import annotations

import os
import webbrowser
from typing import Optional

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget


class ReportViewerWidget(QWidget):
    """Displays the generated HTML replay report."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._engine = None
        self._current_path: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self._open_btn = QPushButton("在浏览器中打开", self)
        self._open_btn.clicked.connect(self._open_in_browser)
        toolbar.addWidget(self._open_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView

            self._engine = QWebEngineView(self)
            layout.addWidget(self._engine)
            self._fallback: Optional[QTextBrowser] = None
        except ImportError:
            self._fallback = QTextBrowser(self)
            self._fallback.setOpenExternalLinks(True)
            layout.addWidget(self._fallback)

    def load(self, html_path: str) -> None:
        self._current_path = html_path
        if not os.path.isfile(html_path):
            return
        if self._engine is not None:
            self._engine.load(QUrl.fromLocalFile(os.path.abspath(html_path)))
        else:
            with open(html_path, "r", encoding="utf-8") as fh:
                self._fallback.setHtml(fh.read())

    def clear(self) -> None:
        self._current_path = None
        if self._engine is not None:
            self._engine.setHtml("")
        else:
            self._fallback.setText("尚未生成报告。完成分析后此处将展示复盘报告。")

    def _open_in_browser(self) -> None:
        if self._current_path and os.path.isfile(self._current_path):
            webbrowser.open(f"file:///{os.path.abspath(self._current_path)}")
