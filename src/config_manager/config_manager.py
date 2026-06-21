"""Configuration & update module.

Wraps :class:`AppConfig` with higher-level operations surfaced to the GUI:
applying a batch of settings, listing available LLM/YOLO backends, checking
the reachability of the local model and pulling offline rule-pack updates.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ..core.config import AppConfig, get_config
from ..core.exceptions import ConfigError
from ..core.logger import get_logger

log = get_logger("config_manager")


class ConfigManager:
    """Facade for configuration editing, persistence and rule updates."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()

    # ----------------------------------------------------------- inspection
    def current(self) -> Dict[str, Any]:
        return self.config.to_dict()

    def available_options(self) -> Dict[str, List[str]]:
        return {
            "analysis_mode": ["fast", "professional"],
            "model_precision": ["low", "medium", "high"],
            "llm_backend": ["ollama", "llama_cpp", "none"],
            "llm_model": ["bakllava", "llava", "moondream"],
        }

    def llm_status(self) -> Dict[str, Any]:
        from ..analysis.llm_client import LLMClient

        client = LLMClient(self.config)
        return {
            "backend": self.config.llm_backend,
            "model": self.config.llm_model,
            "base_url": self.config.ollama_base_url,
            "available": client.is_available(),
        }

    # --------------------------------------------------------- mutation
    def apply_changes(self, changes: Dict[str, Any]) -> AppConfig:
        self.config.update(changes)
        self.config.save()
        log.info("配置已更新并持久化")
        return self.config

    def set_gpu(self, enabled: bool) -> None:
        self.config.gpu_enabled = bool(enabled)
        self.config.save()

    # ----------------------------------------------------- rule-pack update
    def check_rule_updates(self) -> Dict[str, Any]:
        rules_file = os.path.join(self.config.data_dir, "rules_version.json")
        version = self._local_rule_version()
        return {
            "current_version": version,
            "latest_version": "1.0.0",
            "update_available": False,
            "rules_file": rules_file,
        }

    def update_rules(self) -> Dict[str, Any]:
        import json

        version = "1.0.0"
        rules = {
            "version": version,
            "categories": ["teamfight", "laning", "resource_control",
                           "objective", "roaming", "general"],
            "action_types": ["positioning", "skill_usage", "item_usage",
                             "resource_allocation", "vision_control"],
        }
        path = os.path.join(self.config.data_dir, "rules_version.json")
        os.makedirs(self.config.data_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rules, fh, indent=2, ensure_ascii=False)
        log.info("离线规则库已更新到 %s", version)
        return {"version": version, "path": path, "updated": True}

    def _local_rule_version(self) -> str:
        import json

        path = os.path.join(self.config.data_dir, "rules_version.json")
        if not os.path.exists(path):
            return "0.0.0"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("version", "0.0.0")
        except (OSError, ValueError):
            return "0.0.0"

    # ------------------------------------------------------- maintenance
    def clear_cache(self) -> int:
        from ..core.database import Database

        db = Database(self.config.db_path)
        try:
            return db.clear_cache()
        finally:
            db.close()

    def clear_temp_files(self) -> Dict[str, int]:
        cleared: Dict[str, int] = {}
        for key in ("frames_dir", "cache_dir", "screenshots_dir"):
            target = self.config.paths[key]
            count = 0
            if os.path.isdir(target):
                for name in os.listdir(target):
                    p = os.path.join(target, name)
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                            count += 1
                        elif os.path.isdir(p):
                            self._rmtree(p)
                            count += 1
                    except OSError:
                        continue
            cleared[key] = count
        log.info("临时文件已清理: %s", cleared)
        return cleared

    @staticmethod
    def _rmtree(path: str) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
