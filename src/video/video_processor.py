"""Recording processing module.

Responsible for decoding competitive-game recordings, sampling a frame
sequence at a configurable rate, normalising resolution / denoising every
frame, and detecting scene-cut key frames with histogram differencing.

When no real recording is available (placeholder ``<test-data>`` path or a
missing file) the module transparently synthesises deterministic demo frames
so the rest of the pipeline can still be exercised end-to-end.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

import cv2
import numpy as np

from ..core.config import AppConfig
from ..core.exceptions import VideoProcessingError
from ..core.logger import get_logger

log = get_logger("video")

TARGET_WIDTH = 1280
TARGET_HEIGHT = 720


class VideoProcessor:
    """Decode, sample, pre-process and key-frame a recording."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sample_fps = config.frame_sample_fps
        self.frames_dir = config.frames_dir

    # ----------------------------------------------------------------- probe
    def probe(self, video_path: str) -> Dict:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise VideoProcessingError(f"无法打开录像文件: {video_path}")
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = frame_count / fps if fps > 0 else 0.0
            return {
                "duration_sec": duration,
                "fps": fps,
                "width": width,
                "height": height,
                "frame_count": frame_count,
            }
        finally:
            cap.release()

    # -------------------------------------------------------- frame extraction
    def extract_frames(
        self,
        video_path: str,
        match_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> List[Dict]:
        if not video_path or "<test-data>" in video_path or not os.path.isfile(video_path):
            log.info("未提供真实录像，生成演示帧序列: %s", video_path)
            return self.generate_demo_frames(match_id, should_stop=should_stop)

        info = self.probe(video_path)
        out_dir = os.path.join(self.frames_dir, match_id)
        os.makedirs(out_dir, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise VideoProcessingError(f"无法打开录像文件: {video_path}")

        src_fps = info["fps"] or 30.0
        step = max(1, int(round(src_fps / self.sample_fps)))
        total = info["frame_count"]
        frames_info: List[Dict] = []
        idx = 0
        saved = 0
        try:
            while True:
                if should_stop and should_stop():
                    log.info("抽帧已取消 match=%s", match_id)
                    cap.release()
                    return frames_info
                ok, frame = cap.read()
                if not ok:
                    break
                if idx % step == 0:
                    proc = self.preprocess(frame)
                    fname = f"frame_{saved:06d}.jpg"
                    fpath = os.path.join(out_dir, fname)
                    cv2.imwrite(fpath, proc, [cv2.IMWRITE_JPEG_QUALITY, 88])
                    ts = idx / src_fps if src_fps else 0.0
                    frames_info.append(
                        {"frame_idx": saved, "timestamp": ts, "path": fpath}
                    )
                    saved += 1
                    if on_progress:
                        on_progress(idx, total)
                idx += 1
        finally:
            cap.release()

        log.info("从 %s 抽取 %d 帧", video_path, len(frames_info))
        return frames_info

    # ---------------------------------------------------------- pre-processing
    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        if frame is None:
            return np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
        h, w = frame.shape[:2]
        scale = min(TARGET_WIDTH / w, TARGET_HEIGHT / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
        x_off = (TARGET_WIDTH - new_w) // 2
        y_off = (TARGET_HEIGHT - new_h) // 2
        canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
        try:
            canvas = cv2.fastNlMeansDenoisingColored(canvas, None, 5, 5, 7, 21)
        except cv2.error:
            pass
        return canvas

    # ----------------------------------------------------------- key frames
    def extract_keyframes(
        self, frames_info: List[Dict], threshold: float = 30.0
    ) -> List[Dict]:
        if len(frames_info) <= 1:
            for item in frames_info:
                item["is_keyframe"] = True
            return list(frames_info)

        prev_hist = None
        keyframes: List[Dict] = []
        for item in frames_info:
            path = item["path"]
            img = cv2.imread(path) if os.path.exists(path) else None
            if img is None:
                img = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
            cv2.normalize(hist, hist)
            is_key = prev_hist is None
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA) * 100
                if diff >= threshold:
                    is_key = True
            item["is_keyframe"] = is_key
            if is_key:
                keyframes.append(item)
            prev_hist = hist

        if not keyframes:
            frames_info[-1]["is_keyframe"] = True
            keyframes.append(frames_info[-1])
        log.info("关键帧检测: %d / %d", len(keyframes), len(frames_info))
        return keyframes

    # ------------------------------------------------------------- demo data
    def generate_demo_frames(
        self,
        match_id: str,
        count: int = 30,
        duration_sec: float = 1830.0,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> List[Dict]:
        out_dir = os.path.join(self.frames_dir, match_id)
        os.makedirs(out_dir, exist_ok=True)
        frames_info: List[Dict] = []
        ts_step = duration_sec / count if count else 0.0
        for i in range(count):
            if should_stop and should_stop():
                log.info("演示帧生成已取消 match=%s", match_id)
                return frames_info
            ts = i * ts_step
            img = self._render_demo_frame(i, count)
            fname = f"frame_{i:06d}.jpg"
            fpath = os.path.join(out_dir, fname)
            cv2.imwrite(fpath, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
            frames_info.append({"frame_idx": i, "timestamp": ts, "path": fpath})
        log.info("生成 %d 张演示帧到 %s", count, out_dir)
        return frames_info

    @staticmethod
    def _render_demo_frame(index: int, total: int) -> np.ndarray:
        img = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
        ratio = index / max(1, total - 1)
        for y in range(TARGET_HEIGHT):
            base = int(30 + 60 * ratio + 40 * (y / TARGET_HEIGHT))
            img[y, :] = (base, base + 20, base + 40)
        cx, cy = TARGET_WIDTH // 2, TARGET_HEIGHT // 2
        cv2.circle(img, (cx, cy), 120, (60, 80, 120), 3)
        label = f"DEMO FRAME {index+1}/{total}"
        cv2.putText(img, label, (cx - 160, cy + 8), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, "TacticalReplay", (40, 60), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (220, 220, 220), 1, cv2.LINE_AA)
        return img
