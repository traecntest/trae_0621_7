"""Main application window.

Assembles the recording list, timeline, video player, event table, report
viewer and configuration dialog into a single MDI-style workspace.  Long
running analysis is delegated to :class:`AnalysisWorker` so the UI stays
responsive and the window can be minimised while analysis runs in the
background.
"""

from __future__ import annotations

import os
import uuid
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..analysis.llm_client import LLMClient
from ..config_manager.config_manager import ConfigManager
from ..core.config import AppConfig, get_config
from ..core.database import Database, init_test_data
from ..core.models import (
    ActionType,
    AnalysisMode,
    Decision,
    EvaluationLevel,
    EventCategory,
    GameEvent,
    MatchMetadata,
    MatchStatus,
)
from .analysis_worker import AnalysisWorker
from .config_dialog import ConfigDialog
from .report_viewer import ReportViewerWidget
from .styles import APP_QSS
from .timeline_widget import TimelineWidget
from .video_player import VideoPlayerWidget


_CATEGORY_LABELS = {
    EventCategory.TEAMFIGHT: "团战",
    EventCategory.LANING: "对线",
    EventCategory.RESOURCE_CONTROL: "资源控制",
    EventCategory.OBJECTIVE: "目标",
    EventCategory.ROAMING: "游走",
    EventCategory.GENERAL: "通用",
}

_EVAL_LABELS = {
    EvaluationLevel.GOOD: "良好",
    EvaluationLevel.ACCEPTABLE: "尚可",
    EvaluationLevel.SUBOPTIMAL: "欠佳",
    EvaluationLevel.MISTAKE: "失误",
}

_EVAL_COLORS = {
    EvaluationLevel.GOOD: "#4caf50",
    EvaluationLevel.ACCEPTABLE: "#1e88e5",
    EvaluationLevel.SUBOPTIMAL: "#fb8c00",
    EvaluationLevel.MISTAKE: "#e53935",
}

_ACTION_LABELS = {
    ActionType.POSITIONING: "走位",
    ActionType.SKILL_USAGE: "技能释放",
    ActionType.ITEM_USAGE: "装备使用",
    ActionType.RESOURCE_ALLOCATION: "资源分配",
    ActionType.VISION_CONTROL: "视野控制",
}


class MainWindow(QMainWindow):
    """Top-level desktop window."""

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        super().__init__()
        self.config = config or get_config()
        self.db = Database(self.config.db_path)
        self.worker: Optional[AnalysisWorker] = None
        self._current_match: Optional[MatchMetadata] = None
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(400)
        self._play_timer.timeout.connect(self._tick_playback)

        self.setWindowTitle("TacticalReplay · 竞技复盘分析系统")
        self.resize(1280, 820)
        self._build_actions()
        self._build_ui()
        self._refresh_matches()
        self._seed_if_empty()

    # ------------------------------------------------------------- menu / toolbar
    def _build_actions(self) -> None:
        tb = self.addToolBar("主工具栏")
        tb.setMovable(False)

        self.act_import = QAction("导入录像", self)
        self.act_import.triggered.connect(self.import_recording)
        tb.addAction(self.act_import)

        self.act_analyze = QAction("开始分析", self)
        self.act_analyze.triggered.connect(self.start_analysis)
        tb.addAction(self.act_analyze)

        self.act_stop = QAction("停止", self)
        self.act_stop.triggered.connect(self.stop_analysis)
        self.act_stop.setEnabled(False)
        tb.addAction(self.act_stop)

        tb.addSeparator()
        self.act_config = QAction("配置", self)
        self.act_config.triggered.connect(self.open_config)
        tb.addAction(self.act_config)

        self.act_clean = QAction("清理临时文件", self)
        self.act_clean.triggered.connect(self.clean_temp)
        tb.addAction(self.act_clean)

        tb.addSeparator()
        self.act_testdata = QAction("载入测试数据", self)
        self.act_testdata.triggered.connect(self.load_test_data)
        tb.addAction(self.act_testdata)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal, central)

        self.match_tree = QTreeWidget(self)
        self.match_tree.setHeaderLabels(["对局", "状态", "评分"])
        self.match_tree.setColumnWidth(0, 220)
        self.match_tree.itemClicked.connect(self._on_match_selected)
        splitter.addWidget(self.match_tree)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.video_player = VideoPlayerWidget(self)
        right_layout.addWidget(self.video_player, 3)

        self.timeline = TimelineWidget(self)
        self.timeline.positionChanged.connect(self._on_timeline_seek)
        self.timeline.eventClicked.connect(self._on_event_clicked)
        right_layout.addWidget(self.timeline)

        play_bar = QHBoxLayout()
        self.play_btn = QPushButton("播放", self)
        self.play_btn.clicked.connect(self._toggle_play)
        self.heat_btn = QPushButton("热区标注: 开", self)
        self.heat_btn.clicked.connect(self._toggle_heatmap)
        self.time_label = QLabel("00:00 / 00:00", self)
        play_bar.addWidget(self.play_btn)
        play_bar.addWidget(self.heat_btn)
        play_bar.addStretch()
        play_bar.addWidget(self.time_label)
        right_layout.addLayout(play_bar)

        self.tabs = QTabWidget(self)
        self.event_table = QTableWidget(0, 5, self)
        self.event_table.setHorizontalHeaderLabels(
            ["时间", "分类", "事件", "置信度", "描述"]
        )
        self.event_table.setAlternatingRowColors(True)
        self.event_table.itemDoubleClicked.connect(self._on_event_double_clicked)
        self.tabs.addTab(self.event_table, "关键事件")

        self.decision_table = QTableWidget(0, 5, self)
        self.decision_table.setHorizontalHeaderLabels(
            ["时间", "操作类型", "意图", "评估", "理由"]
        )
        self.decision_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.decision_table, "决策分析")

        self.report_viewer = ReportViewerWidget(self)
        self.tabs.addTab(self.report_viewer, "复盘报告")
        right_layout.addWidget(self.tabs, 2)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        outer.addWidget(self.progress_bar)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

    # ----------------------------------------------------------- match handling
    def _refresh_matches(self) -> None:
        self.match_tree.clear()
        matches = self.db.list_matches()
        for m in matches:
            item = QTreeWidgetItem([
                f"{m.game_name} · {m.player_name}",
                m.status.value,
                f"{m.overall_score}" if m.overall_score is not None else "-",
            ])
            item.setData(0, Qt.UserRole, m.match_id)
            self.match_tree.addTopLevelItem(item)
        self.statusBar().showMessage(f"共 {len(matches)} 场对局", 3000)

    def _on_match_selected(self, item: QTreeWidgetItem) -> None:
        match_id = item.data(0, Qt.UserRole)
        match = self.db.get_match(match_id)
        if not match:
            return
        self._current_match = match
        self._ensure_frames(match)
        events = self.db.get_events(match_id)
        decisions = self.db.get_decisions(match_id)
        self.timeline.set_data(match.duration_sec, events)
        self.video_player.set_events(events)
        self._populate_events(events)
        self._populate_decisions(decisions)
        if match.report_path and os.path.isfile(match.report_path):
            self.report_viewer.load(match.report_path)
        else:
            self.report_viewer.clear()
        self._update_time_label(0.0)
        self.progress_bar.setValue(int(match.progress * 100))
        self._show_frame_at(0.0)
        status_map = {
            MatchStatus.PENDING: "等待分析（点击“开始分析”）",
            MatchStatus.RUNNING: f"分析中… {match.progress:.0%}",
            MatchStatus.DONE: "分析完成",
            MatchStatus.FAILED: "分析失败",
            MatchStatus.CANCELLED: "已取消",
        }
        self.statusBar().showMessage(status_map.get(match.status, match.status.value), 5000)

    def _populate_events(self, events: List[GameEvent]) -> None:
        self.event_table.setRowCount(0)
        for ev in sorted(events, key=lambda e: e.timestamp):
            row = self.event_table.rowCount()
            self.event_table.insertRow(row)
            self.event_table.setItem(row, 0, QTableWidgetItem(self._fmt_ts(ev.timestamp)))
            self.event_table.setItem(row, 1, QTableWidgetItem(_CATEGORY_LABELS.get(ev.category, ev.category.value)))
            self.event_table.setItem(row, 2, QTableWidgetItem(ev.title))
            self.event_table.setItem(row, 3, QTableWidgetItem(f"{ev.confidence:.0%}"))
            self.event_table.setItem(row, 4, QTableWidgetItem(ev.description))

    def _populate_decisions(self, decisions: List[Decision]) -> None:
        self.decision_table.setRowCount(0)
        for dc in sorted(decisions, key=lambda d: d.timestamp):
            row = self.decision_table.rowCount()
            self.decision_table.insertRow(row)
            self.decision_table.setItem(row, 0, QTableWidgetItem(self._fmt_ts(dc.timestamp)))
            self.decision_table.setItem(row, 1, QTableWidgetItem(_ACTION_LABELS.get(dc.action_type, dc.action_type.value)))
            self.decision_table.setItem(row, 2, QTableWidgetItem(dc.intent))
            eval_item = QTableWidgetItem(_EVAL_LABELS.get(dc.evaluation, dc.evaluation.value))
            eval_item.setForeground(Qt.GlobalColor.white)
            self.decision_table.setItem(row, 3, eval_item)
            self.decision_table.setItem(row, 4, QTableWidgetItem(dc.reasoning))

    # ------------------------------------------------------------- actions
    def import_recording(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择录像文件", "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov *.flv);;所有文件 (*)",
        )
        if not path:
            return
        game_name, ok = self._prompt_text("游戏名称", "竞技对决")
        if not ok:
            return
        player_name, ok = self._prompt_text("玩家名称", "Player1")
        if not ok:
            return
        match = MatchMetadata(
            match_id=f"match-{uuid.uuid4().hex[:8]}",
            game_name=game_name,
            player_name=player_name,
            source_path=path,
            duration_sec=0.0,
            analysis_mode=AnalysisMode.PROFESSIONAL,
            status=MatchStatus.PENDING,
        )
        try:
            from ..video.video_processor import VideoProcessor
            vp = VideoProcessor(self.config)
            info = vp.probe(path)
            match.duration_sec = info["duration_sec"] or 0.0
        except Exception:
            match.duration_sec = 0.0
        if match.duration_sec <= 0:
            match.duration_sec = 1800.0
        self.db.upsert_match(match)
        try:
            from ..video.video_processor import VideoProcessor
            vp = VideoProcessor(self.config)
            if os.path.isfile(path):
                vp.extract_frames(path, match.match_id)
            else:
                count = min(180, max(30, int(match.duration_sec * self.config.frame_sample_fps)))
                count = min(count, int(match.duration_sec / 5))
                vp.generate_demo_frames(
                    match.match_id, count=count, duration_sec=match.duration_sec
                )
        except Exception as exc:
            self.statusBar().showMessage(f"抽帧失败: {exc}", 5000)
        self._refresh_matches()
        for i in range(self.match_tree.topLevelItemCount()):
            item = self.match_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == match.match_id:
                self.match_tree.setCurrentItem(item)
                self._on_match_selected(item)
                break
        self.statusBar().showMessage(f"已导入: {game_name}（点击“开始分析”生成复盘报告）", 6000)

    def start_analysis(self) -> None:
        if self.worker and self.worker.is_running():
            QMessageBox.information(self, "提示", "已有分析任务正在运行")
            return
        match = self._current_match
        if match is None:
            items = self.match_tree.selectedItems()
            if items:
                match = self.db.get_match(items[0].data(0, Qt.UserRole))
            if match is None:
                QMessageBox.warning(self, "提示", "请先在左侧选择一场对局")
                return
        if match.status == MatchStatus.DONE:
            ret = QMessageBox.question(
                self, "重新分析", "该对局已分析完成，是否重新分析？"
            )
            if ret != QMessageBox.Yes:
                return
        match.status = MatchStatus.RUNNING
        match.progress = 0.02
        if match.duration_sec <= 0:
            match.duration_sec = 1800.0
        self._ensure_frames(match)
        self.db.upsert_match(match)
        self.progress_bar.setValue(2)
        self.statusBar().showMessage("正在初始化分析…")
        self._refresh_matches()
        self.worker = AnalysisWorker(self.config, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.event.connect(self._on_pipeline_event)
        self.worker.finished.connect(self._on_analysis_done)
        self.worker.failed.connect(self._on_analysis_failed)
        self.worker.start(match)
        self.act_analyze.setEnabled(False)
        self.act_stop.setEnabled(True)
        self.act_import.setEnabled(False)
        self.statusBar().showMessage("分析进行中…可最小化窗口继续其他工作")

    def stop_analysis(self) -> None:
        if self.worker and self.worker.is_running():
            self.worker.stop()
            self.statusBar().showMessage("已请求停止分析")
        self.act_stop.setEnabled(False)
        self.act_analyze.setEnabled(True)
        self.act_import.setEnabled(True)

    def open_config(self) -> None:
        dlg = ConfigDialog(self.config, self)
        if dlg.exec_():
            self.config = get_config()
            self.statusBar().showMessage("配置已更新", 4000)

    def clean_temp(self) -> None:
        cm = ConfigManager(self.config)
        result = cm.clear_temp_files()
        total = sum(result.values())
        QMessageBox.information(self, "清理完成", f"已清理 {total} 项临时文件")

    def load_test_data(self) -> None:
        match = init_test_data(self.db)
        self._generate_report_for(match)
        self._refresh_matches()
        self.statusBar().showMessage(f"测试数据已载入: {match.match_id}", 4000)

    # ---------------------------------------------------------- worker signals
    def _on_progress(self, value: float, message: str) -> None:
        self.progress_bar.setValue(int(value * 100))
        self.statusBar().showMessage(message)
        if self._current_match:
            self._current_match.progress = value
            self._current_match.status = MatchStatus.RUNNING

    def _on_pipeline_event(self, kind: str, payload: dict) -> None:
        if kind == "error":
            QMessageBox.warning(self, "分析错误", payload.get("message", "未知错误"))

    def _on_analysis_done(self, match: MatchMetadata) -> None:
        self.db.upsert_match(match)
        self._refresh_matches()
        self.progress_bar.setValue(100)
        self.statusBar().showMessage("分析完成", 5000)
        self.act_analyze.setEnabled(True)
        self.act_stop.setEnabled(False)
        self.act_import.setEnabled(True)
        self._current_match = match
        if match.report_path:
            self.report_viewer.load(match.report_path)
        events = self.db.get_events(match.match_id)
        decisions = self.db.get_decisions(match.match_id)
        self.timeline.set_data(match.duration_sec, events)
        self.video_player.set_events(events)
        self._populate_events(events)
        self._populate_decisions(decisions)
        self.tabs.setCurrentWidget(self.report_viewer)

    def _on_analysis_failed(self, message: str) -> None:
        self.act_analyze.setEnabled(True)
        self.act_stop.setEnabled(False)
        self.act_import.setEnabled(True)
        self.statusBar().showMessage(f"分析失败: {message}", 6000)
        if self._current_match:
            self._current_match.status = MatchStatus.FAILED
            self._refresh_matches()

    # ---------------------------------------------------------- timeline / play
    def _on_timeline_seek(self, seconds: float) -> None:
        self._show_frame_at(seconds)

    def _on_event_clicked(self, event: GameEvent) -> None:
        self._show_frame_at(event.timestamp)

    def _on_event_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        ts_item = self.event_table.item(row, 0)
        if ts_item:
            mm, ss = ts_item.text().split(":")
            self._show_frame_at(int(mm) * 60 + int(ss))

    def _toggle_play(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_btn.setText("播放")
        else:
            if self._current_match and self._current_match.duration_sec > 0:
                self._play_timer.start()
                self.play_btn.setText("暂停")

    def _toggle_heatmap(self) -> None:
        on = not self.video_player._show_heatmap
        self.video_player.toggle_heatmap(on)
        self.heat_btn.setText("热区标注: 开" if on else "热区标注: 关")

    def _tick_playback(self) -> None:
        if not self._current_match:
            return
        cur = self.timeline._position + 0.5
        if cur >= self._current_match.duration_sec:
            self._play_timer.stop()
            self.play_btn.setText("播放")
            return
        self.timeline.set_position(cur)
        self._show_frame_at(cur)

    def _show_frame_at(self, seconds: float) -> None:
        if not self._current_match:
            return
        self.timeline.set_position(seconds)
        self._update_time_label(seconds)
        frames_dir = os.path.join(self.config.frames_dir, self._current_match.match_id)
        path = self._find_nearest_frame(frames_dir, seconds)
        if path is None:
            self._ensure_frames(self._current_match)
            path = self._find_nearest_frame(frames_dir, seconds)
        idx = int(seconds * self.config.frame_sample_fps)
        from ..vision.ui_detector import UIDetector
        state = UIDetector(self.config).detect(path or "<none>", idx, seconds)
        self.video_player.show_frame(path, state)

    def _find_nearest_frame(self, frames_dir: str, seconds: float) -> Optional[str]:
        if not os.path.isdir(frames_dir):
            return None
        frames = sorted(f for f in os.listdir(frames_dir) if f.startswith("frame_") and f.endswith(".jpg"))
        if not frames:
            return None
        target_idx = int(seconds * self.config.frame_sample_fps)
        best: Optional[str] = None
        best_diff = float("inf")
        for fname in frames:
            try:
                idx = int(fname[6:12])
                diff = abs(idx - target_idx)
                if diff < best_diff:
                    best_diff = diff
                    best = fname
            except (ValueError, IndexError):
                continue
        return os.path.join(frames_dir, best) if best else None

    def _update_time_label(self, seconds: float) -> None:
        dur = self._current_match.duration_sec if self._current_match else 0.0
        self.time_label.setText(f"{self._fmt_ts(seconds)} / {self._fmt_ts(dur)}")

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _fmt_ts(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _prompt_text(self, title: str, default: str) -> tuple:
        from PyQt5.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, title + ":", text=default)

    def _seed_if_empty(self) -> None:
        if not self.db.list_matches():
            match = init_test_data(self.db)
            self._generate_report_for(match)
            self._refresh_matches()
            self.statusBar().showMessage("已自动载入测试数据", 4000)

    def _generate_report_for(self, match: MatchMetadata) -> None:
        from ..report.report_generator import ReportGenerator

        events = self.db.get_events(match.match_id)
        decisions = self.db.get_decisions(match.match_id)
        try:
            path = ReportGenerator(self.config).generate(match, events, decisions)
            match.report_path = path
            match.status = MatchStatus.DONE
            match.progress = 1.0
            self.db.upsert_match(match)
        except Exception as exc:
            self.statusBar().showMessage(f"报告生成失败: {exc}", 5000)

    def _ensure_frames(self, match: MatchMetadata) -> None:
        frames_dir = os.path.join(self.config.frames_dir, match.match_id)
        has_frames = os.path.isdir(frames_dir) and len(os.listdir(frames_dir)) > 0
        if has_frames:
            return
        try:
            from ..video.video_processor import VideoProcessor
            vp = VideoProcessor(self.config)
            if os.path.isfile(match.source_path):
                vp.extract_frames(match.source_path, match.match_id)
            else:
                count = min(180, max(30, int(match.duration_sec * self.config.frame_sample_fps)))
                count = min(count, int(match.duration_sec / 5))
                vp.generate_demo_frames(
                    match.match_id, count=count, duration_sec=match.duration_sec
                )
        except Exception as exc:
            self.statusBar().showMessage(f"准备帧失败: {exc}", 5000)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.worker.is_running():
            self.worker.stop()
        self.db.close()
        super().closeEvent(event)


def run() -> int:
    import sys

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(run())
