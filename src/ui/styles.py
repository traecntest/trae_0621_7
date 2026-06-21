"""Shared Qt stylesheet for the desktop application."""

APP_QSS = """
QWidget {
    background-color: #1e1f26;
    color: #e6e6e6;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background-color: #1e1f26; }

QPushButton {
    background-color: #2a2d36;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    padding: 7px 16px;
    color: #e6e6e6;
}
QPushButton:hover { background-color: #353944; border-color: #4caf50; }
QPushButton:pressed { background-color: #1f2229; }
QPushButton:disabled { color: #666; border-color: #2a2d36; }
QPushButton#primaryBtn { background-color: #4caf50; color: #fff; border: none; }
QPushButton#primaryBtn:hover { background-color: #5cbf60; }
QPushButton#dangerBtn { background-color: #c62828; color: #fff; border: none; }
QPushButton#dangerBtn:hover { background-color: #d63232; }

QListWidget, QTreeWidget, QTableWidget {
    background-color: #262932;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    alternate-background-color: #2a2d36;
}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
    background-color: #4caf50; color: #fff;
}
QHeaderView::section {
    background-color: #2a2d36;
    border: none;
    padding: 6px;
    border-bottom: 1px solid #3a3f4b;
}

QProgressBar {
    background-color: #2a2d36;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    text-align: center;
    height: 18px;
}
QProgressBar::chunk { background-color: #4caf50; border-radius: 5px; }

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background-color: #2a2d36;
    border: 1px solid #3a3f4b;
    border-radius: 5px;
    padding: 5px 8px;
}
QComboBox QAbstractItemView { background-color: #2a2d36; selection-background-color: #4caf50; }

QTabWidget::pane { border: 1px solid #3a3f4b; border-radius: 6px; }
QTabBar::tab {
    background-color: #2a2d36;
    padding: 7px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #4caf50; color: #fff; }

QStatusBar { background-color: #1a1b20; }
QToolTip { background-color: #353944; color: #fff; border: 1px solid #4caf50; }

QScrollBar:vertical { background: #1e1f26; width: 10px; }
QScrollBar::handle:vertical { background: #3a3f4b; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #4caf50; }
QScrollBar:horizontal { background: #1e1f26; height: 10px; }
QScrollBar::handle:horizontal { background: #3a3f4b; border-radius: 5px; }

QGroupBox {
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
"""
