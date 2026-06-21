"""Plugin manager for game-specific rule engines.

The system ships game-agnostic analysis.  Individual games (MOBA, FPS, RTS)
can ship a plugin that implements the :class:`GamePlugin` contract to inject
custom UI regions, event heuristics and report categories.  Plugins are plain
Python modules placed in ``data/plugins`` and discovered dynamically so new
games can be added without touching the core.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
from typing import Dict, List, Optional, Type

from ..core.config import AppConfig
from ..core.exceptions import PluginError
from ..core.logger import get_logger
from ..core.models import EventCategory, MatchMetadata

log = get_logger("plugin")


class GamePlugin:
    """Base contract every game rule-engine plugin must implement."""

    name: str = "base"
    game_matchers: List[str] = []
    supported_categories: List[EventCategory] = []

    def matches(self, game_name: str) -> bool:
        g = (game_name or "").lower()
        return any(m.lower() in g for m in self.game_matchers)

    def ui_regions(self) -> Dict[str, tuple]:
        return {}

    def custom_event_title(self, category: EventCategory, timestamp: float) -> str:
        return ""

    def enrich_summary(self, match: MatchMetadata, summary: str) -> str:
        return summary


class PluginManager:
    """Discovers and loads game plugins from the configured directory."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.plugins_dir = config.plugins_dir
        self._plugins: List[GamePlugin] = []
        self._loaded = False

    def discover(self) -> List[GamePlugin]:
        if self._loaded:
            return self._plugins
        os.makedirs(self.plugins_dir, exist_ok=True)
        for fname in os.listdir(self.plugins_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            path = os.path.join(self.plugins_dir, fname)
            try:
                plugin = self._load_plugin_file(path)
                if plugin is not None:
                    self._plugins.append(plugin)
                    log.info("已加载插件: %s (%s)", plugin.name, fname)
            except Exception as exc:
                log.warning("加载插件 %s 失败: %s", fname, exc)
        if not self._plugins:
            self._plugins.append(self._builtin_fallback())
        self._loaded = True
        return self._plugins

    def _load_plugin_file(self, path: str) -> Optional[GamePlugin]:
        modname = "plugin_" + os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, GamePlugin)
                and obj is not GamePlugin
                and obj.__module__ == module.__name__
            ):
                return obj()
        return None

    def select_for(self, game_name: str) -> GamePlugin:
        plugins = self.discover()
        for p in plugins:
            if p.matches(game_name):
                return p
        return plugins[-1]

    @staticmethod
    def _builtin_fallback() -> GamePlugin:
        return GamePlugin()
