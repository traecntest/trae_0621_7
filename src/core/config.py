"""Application configuration.

``AppConfig`` is the single source of truth for every tunable knob: paths,
model precision, analysis granularity, GPU acceleration, LLM backend, etc.
It persists itself as JSON so that user choices survive restarts and can be
edited by the configuration & update module.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict

from .exceptions import ConfigError


def _default_paths(base: str) -> Dict[str, str]:
    return {
        "data_dir": os.path.join(base, "data"),
        "db_path": os.path.join(base, "data", "replay.db"),
        "recordings_dir": os.path.join(base, "data", "recordings"),
        "frames_dir": os.path.join(base, "data", "frames"),
        "screenshots_dir": os.path.join(base, "data", "screenshots"),
        "reports_dir": os.path.join(base, "data", "reports"),
        "cache_dir": os.path.join(base, "data", "cache"),
        "plugins_dir": os.path.join(base, "plugins"),
        "config_path": os.path.join(base, "data", "config.json"),
    }


@dataclass
class AppConfig:
    """Runtime configuration for the whole application."""

    app_name: str = "TacticalReplay"
    version: str = "1.0.0"

    analysis_mode: str = "professional"
    model_precision: str = "medium"
    analysis_granularity: float = 1.0
    gpu_enabled: bool = False
    frame_sample_fps: float = 2.0
    cache_enabled: bool = True

    llm_backend: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "bakllava"

    yolo_onnx_path: str = ""
    confidence_threshold: float = 0.35

    paths: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paths:
            self.paths = _default_paths(self._project_root())

    # ------------------------------------------------------------------ paths
    @staticmethod
    def _project_root() -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, "..", ".."))

    @property
    def data_dir(self) -> str:
        return self.paths["data_dir"]

    @property
    def db_path(self) -> str:
        return self.paths["db_path"]

    @property
    def recordings_dir(self) -> str:
        return self.paths["recordings_dir"]

    @property
    def frames_dir(self) -> str:
        return self.paths["frames_dir"]

    @property
    def screenshots_dir(self) -> str:
        return self.paths["screenshots_dir"]

    @property
    def reports_dir(self) -> str:
        return self.paths["reports_dir"]

    @property
    def cache_dir(self) -> str:
        return self.paths["cache_dir"]

    @property
    def plugins_dir(self) -> str:
        return self.paths["plugins_dir"]

    # ------------------------------------------------------------- lifecycle
    def ensure_directories(self) -> None:
        for key in (
            "data_dir",
            "recordings_dir",
            "frames_dir",
            "screenshots_dir",
            "reports_dir",
            "cache_dir",
            "plugins_dir",
        ):
            os.makedirs(self.paths[key], exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str | None = None) -> str:
        target = path or self.paths["config_path"]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        return target

    @classmethod
    def load(cls, path: str | None = None) -> "AppConfig":
        cfg = cls()
        target = path or cfg.paths["config_path"]
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigError(f"无法读取配置文件 {target}: {exc}") from exc
            stored_paths = data.get("paths", {})
            cfg.paths.update(stored_paths)
            for key, value in data.items():
                if key == "paths":
                    continue
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        return cfg

    def update(self, changes: Dict[str, Any]) -> None:
        """Apply a partial update and validate critical fields."""
        for key, value in changes.items():
            if not hasattr(cfg := self, key):
                continue
            if key in ("analysis_mode",) and value not in ("fast", "professional"):
                raise ConfigError(f"非法的分析模式: {value}")
            if key == "model_precision" and value not in ("low", "medium", "high"):
                raise ConfigError(f"非法的模型精度: {value}")
            if key == "analysis_granularity" and not (0.1 <= float(value) <= 2.0):
                raise ConfigError("分析粒度应在 0.1~2.0 之间")
            setattr(self, key, value)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the process-wide singleton configuration."""
    global _config
    if _config is None:
        _config = AppConfig.load()
        _config.ensure_directories()
    return _config


def reset_config() -> None:
    """Reset the cached singleton (mainly for tests)."""
    global _config
    _config = None
