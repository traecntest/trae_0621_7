from __future__ import annotations

import os
import random

import cv2
import numpy as np

from ..core.config import AppConfig
from ..core.exceptions import VisionDetectionError
from ..core.logger import get_logger
from ..core.models import FrameState, HeroPosition, SkillState
from .yolo_detector import YOLODetector

_HERO_NAMES = ["Hero_A", "Hero_B", "Hero_C", "Hero_D", "Hero_E"]
_TEAMS = ["blue", "blue", "blue", "red", "red"]
_SKILL_NAMES = ["Skill_Q", "Skill_W", "Skill_E", "Skill_R"]
_SKILL_COOLDOWNS = [4.0, 8.0, 12.0, 60.0]
_ITEM_POOL = ["Sword", "Boots", "Potion", "Shield", "Bow", "Ring", "Cloak", "Wand"]
_MINIMAP_LABELS = ["top_lane", "mid_lane", "bot_lane", "jungle", "base"]
_ROIS_1280_720 = {
    "minimap": (1020, 470, 1280, 720),
    "skillbar": (490, 650, 790, 720),
    "items": (20, 650, 280, 720),
    "hp": (0, 0, 1280, 120),
}


class UIDetector:
    def __init__(self, config: AppConfig):
        self.config = config
        self.detector = YOLODetector(
            config.yolo_onnx_path,
            config.confidence_threshold,
            config.gpu_enabled,
        )
        self.logger = get_logger("vision")

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
        return blurred

    def crop_regions(self, frame: np.ndarray) -> dict:
        h, w = frame.shape[:2]
        result = {}
        for name, (x1, y1, x2, y2) in _ROIS_1280_720.items():
            xa = max(0, x1)
            ya = max(0, y1)
            xb = min(w, x2)
            yb = min(h, y2)
            if xb <= xa or yb <= ya:
                result[name] = np.zeros((1, 1, 3), dtype=np.uint8)
            else:
                result[name] = frame[ya:yb, xa:xb]
        return result

    def detect(self, frame_path: str, frame_idx: int, timestamp: float) -> FrameState:
        frame = None
        if frame_path and os.path.exists(frame_path):
            frame = cv2.imread(frame_path)
            if frame is None:
                raise VisionDetectionError(f"无法读取帧图像: {frame_path}")
        if frame is None:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        if self.detector.is_available():
            detections = self.detector.detect(frame)
            state = self._state_from_detections(detections, frame_idx, timestamp)
        else:
            state = self._mock_detect(frame_idx, timestamp)
        state.screenshot_path = frame_path
        return state

    def _state_from_detections(self, detections, frame_idx: int, timestamp: float) -> FrameState:
        hero_positions = []
        skill_states = []
        items = []
        hp_values = {}
        minimap_region = None
        for det in detections:
            cn = str(det.get("class_name", "")).lower()
            bbox = list(det.get("bbox", [0.0, 0.0, 0.0, 0.0])) + [0.0, 0.0, 0.0, 0.0]
            x, y, bw, bh = bbox[0], bbox[1], bbox[2], bbox[3]
            if "hero" in cn:
                hero_positions.append(
                    HeroPosition(name=cn, team="blue", x=float(x), y=float(y))
                )
            elif "skill" in cn:
                skill_states.append(
                    SkillState(skill_name=cn, ready=True, cooldown_remaining=0.0)
                )
            elif "item" in cn:
                items.append(cn)
            elif "hp" in cn or "health" in cn:
                hp_values[cn] = float(bh)
            elif "minimap" in cn:
                minimap_region = cn
        return FrameState(
            frame_idx=frame_idx,
            timestamp=timestamp,
            hero_positions=hero_positions,
            skill_states=skill_states,
            items=items,
            hp_values=hp_values,
            gold=0,
            minimap_region=minimap_region,
        )

    def _mock_detect(self, frame_idx: int, timestamp: float) -> FrameState:
        rng = random.Random(frame_idx)
        hero_positions = []
        for i, name in enumerate(_HERO_NAMES):
            bx = rng.uniform(10.0, 90.0)
            by = rng.uniform(10.0, 90.0)
            x = (bx + timestamp * 3.0) % 100.0
            y = (by + timestamp * 1.5) % 100.0
            alive = rng.random() > 0.1
            hp = round(rng.uniform(20.0, 100.0), 1) if alive else 0.0
            hero_positions.append(
                HeroPosition(
                    name=name,
                    team=_TEAMS[i],
                    x=round(x, 2),
                    y=round(y, 2),
                    alive=alive,
                    hp_percent=hp,
                )
            )
        skill_states = []
        for i, name in enumerate(_SKILL_NAMES):
            cd = _SKILL_COOLDOWNS[i]
            phase = timestamp % cd
            if phase < cd * 0.3:
                ready = True
                remaining = 0.0
            else:
                ready = False
                remaining = round(cd - phase, 2)
            skill_states.append(
                SkillState(skill_name=name, ready=ready, cooldown_remaining=remaining)
            )
        num_items = min(len(_ITEM_POOL), int(timestamp / 30))
        items = rng.sample(_ITEM_POOL, k=num_items)
        hp_values = {h.name: h.hp_percent for h in hero_positions}
        gold = int(timestamp * 12.5)
        minimap_region = _MINIMAP_LABELS[int(timestamp / 20) % len(_MINIMAP_LABELS)]
        return FrameState(
            frame_idx=frame_idx,
            timestamp=timestamp,
            hero_positions=hero_positions,
            skill_states=skill_states,
            items=items,
            hp_values=hp_values,
            gold=gold,
            minimap_region=minimap_region,
        )
