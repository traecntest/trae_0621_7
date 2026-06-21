"""Configuration dialog.

Lets the user choose AI model precision, analysis granularity, GPU
acceleration, LLM backend / model and trigger offline rule-pack updates.
"""

from __future__ import annotations

from typing import Dict

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..config_manager.config_manager import ConfigManager
from ..core.config import AppConfig


class ConfigDialog(QDialog):
    """Modal settings dialog backed by :class:`ConfigManager`."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.manager = ConfigManager(config)
        self.setWindowTitle("系统配置")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        analysis_box = QGroupBox("分析与性能", self)
        form = QFormLayout(analysis_box)
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(["fast", "professional"])
        self.precision_combo = QComboBox(self)
        self.precision_combo.addItems(["low", "medium", "high"])
        self.granularity_spin = QDoubleSpinBox(self)
        self.granularity_spin.setRange(0.1, 2.0)
        self.granularity_spin.setSingleStep(0.1)
        self.gpu_check = QCheckBox("启用 GPU 加速", self)
        form.addRow("分析模式", self.mode_combo)
        form.addRow("模型精度", self.precision_combo)
        form.addRow("分析粒度", self.granularity_spin)
        form.addRow(self.gpu_check)
        layout.addWidget(analysis_box)

        llm_box = QGroupBox("多模态大模型", self)
        llm_form = QFormLayout(llm_box)
        self.llm_model_combo = QComboBox(self)
        self.llm_model_combo.addItems(["bakllava", "llava", "moondream"])
        self.status_label = QLabel("检测中…", self)
        self.check_btn = QPushButton("检测可用性", self)
        self.check_btn.clicked.connect(self._check_llm)
        llm_form.addRow("模型", self.llm_model_combo)
        llm_form.addRow("状态", self.status_label)
        llm_form.addRow(self.check_btn)
        layout.addWidget(llm_box)

        rules_box = QGroupBox("离线规则库", self)
        rules_form = QFormLayout(rules_box)
        self.rule_label = QLabel("版本: -", self)
        self.update_btn = QPushButton("更新规则库", self)
        self.update_btn.clicked.connect(self._update_rules)
        rules_form.addRow(self.rule_label)
        rules_form.addRow(self.update_btn)
        layout.addWidget(rules_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_current(self) -> None:
        self.mode_combo.setCurrentText(self.config.analysis_mode)
        self.precision_combo.setCurrentText(self.config.model_precision)
        self.granularity_spin.setValue(self.config.analysis_granularity)
        self.gpu_check.setChecked(self.config.gpu_enabled)
        self.llm_model_combo.setCurrentText(self.config.llm_model)
        info = self.manager.check_rule_updates()
        self.rule_label.setText(f"当前版本: {info['current_version']}  最新: {info['latest_version']}")
        self._check_llm()

    def _check_llm(self) -> None:
        status = self.manager.llm_status()
        text = "可用" if status["available"] else "不可用 (未检测到本地模型)"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color:#4caf50;" if status["available"] else "color:#e53935;"
        )

    def _update_rules(self) -> None:
        result = self.manager.update_rules()
        self.rule_label.setText(f"已更新到版本: {result['version']}")
        QMessageBox.information(self, "规则库", f"离线规则库已更新到 {result['version']}")

    def _save(self) -> None:
        changes: Dict[str, object] = {
            "analysis_mode": self.mode_combo.currentText(),
            "model_precision": self.precision_combo.currentText(),
            "analysis_granularity": self.granularity_spin.value(),
            "gpu_enabled": self.gpu_check.isChecked(),
            "llm_model": self.llm_model_combo.currentText(),
        }
        try:
            self.manager.apply_changes(changes)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
