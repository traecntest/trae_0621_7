"""Business-logic orchestrator.

Coordinates the four-stage analysis pipeline (video -> vision -> decision ->
report) and exposes a small observer API so the presentation layer can show
live progress without taking a hard dependency on Qt.  The pipeline runs on a
background :mod:`threading` thread and communicates through thread-safe
callbacks.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable, List, Optional

from ..analysis.decision_analyzer import DecisionAnalyzer
from ..core.config import AppConfig
from ..core.database import Database
from ..core.exceptions import ReplayError
from ..core.logger import get_logger
from ..core.models import (
    AnalysisResult,
    FrameState,
    MatchMetadata,
    MatchStatus,
)
from ..report.report_generator import ReportGenerator
from ..video.video_processor import VideoProcessor
from ..vision.ui_detector import UIDetector

log = get_logger("orchestrator")

ProgressCallback = Callable[[float, str], None]
EventCallback = Callable[[str, dict], None]


class AnalysisPipeline:
    """Run the full analysis flow for one recording."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.video = VideoProcessor(config)
        self.detector = UIDetector(config)
        self.analyzer = DecisionAnalyzer(config)
        self.reporter = ReportGenerator(config)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ----------------------------------------------------------- scheduling
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()

    def run_async(
        self,
        match: MatchMetadata,
        on_progress: Optional[ProgressCallback] = None,
        on_event: Optional[EventCallback] = None,
        on_done: Optional[Callable[[MatchMetadata], None]] = None,
        on_error: Optional[Callable[[MatchMetadata, str], None]] = None,
    ) -> None:
        if self.is_running():
            raise RuntimeError("已有分析任务正在运行")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(match, on_progress, on_event, on_done, on_error),
            daemon=True,
            name=f"analyze-{match.match_id}",
        )
        self._thread.start()

    # ------------------------------------------------------------- execution
    def _run(self, match, on_progress, on_event, on_done, on_error):
        db = Database(self.config.db_path)
        try:
            self._emit(on_progress, 0.02, "准备录像处理", match, on_event, db)
            frames_info = self.video.extract_frames(
                match.source_path, match.match_id,
                on_progress=lambda cur, total: self._emit(
                    on_progress, 0.05 + 0.20 * (cur / max(1, total)),
                    f"抽取帧 {cur}/{total}", match, on_event, db,
                ),
            )

            self._emit(on_progress, 0.28, "检测游戏 UI 元素", match, on_event, db)
            frame_states: List[FrameState] = []
            total = max(1, len(frames_info))
            for i, info in enumerate(frames_info):
                if self._stop.is_set():
                    match.status = MatchStatus.CANCELLED
                    db.upsert_match(match)
                    return
                fs = self.detector.detect(info["path"], info["frame_idx"], info["timestamp"])
                frame_states.append(fs)
                self._emit(
                    on_progress, 0.28 + 0.32 * (i / total),
                    f"视觉识别 {i+1}/{total}", match, on_event, db,
                )

            self._emit(on_progress, 0.62, "调用决策分析", match, on_event, db)
            result: AnalysisResult = self.analyzer.analyze(match, frame_states)
            for ev in result.events:
                db.insert_event(ev)
            for dc in result.decisions:
                db.insert_decision(match.match_id, dc)

            self._emit(on_progress, 0.85, "生成复盘报告", match, on_event, db)
            report_path = self.reporter.generate(
                match, result.events, result.decisions
            )
            match.report_path = report_path
            match.overall_score = result.overall_score
            match.summary = result.summary
            self._emit(on_progress, 1.0, "分析完成", match, on_event, db)
            match.status = MatchStatus.DONE
            match.progress = 1.0
            db.upsert_match(match)

            if on_event:
                on_event("done", {"report_path": report_path, "score": result.overall_score})
            if on_done:
                on_done(match)
        except ReplayError as exc:
            log.exception("分析失败 match=%s", match.match_id)
            match.status = MatchStatus.FAILED
            db.upsert_match(match)
            if on_event:
                on_event("error", {"message": str(exc)})
            if on_error:
                on_error(match, str(exc))
        except Exception as exc:
            log.exception("分析意外异常 match=%s", match.match_id)
            match.status = MatchStatus.FAILED
            db.upsert_match(match)
            tb = traceback.format_exc()
            if on_event:
                on_event("error", {"message": str(exc), "traceback": tb})
            if on_error:
                on_error(match, str(exc))
        finally:
            db.close()

    # --------------------------------------------------------------- helpers
    def _emit(self, on_progress, value, message, match, on_event, db):
        match.progress = value
        match.status = MatchStatus.RUNNING
        db.upsert_match(match)
        if on_progress:
            on_progress(value, message)
        if on_event:
            on_event("progress", {"value": value, "message": message})
