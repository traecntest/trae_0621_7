"""Sample game rule-engine plugin for MOBA-style competitive titles."""

from __future__ import annotations

from typing import Dict

from src.plugins.plugin_manager import GamePlugin


class MobaNovaPlugin(GamePlugin):
    name = "MobaNova"
    game_matchers = ["星耀峡谷", "moba", "竞技对决"]

    def ui_regions(self) -> Dict[str, tuple]:
        return {
            "minimap": (1056, 576, 1280, 720),
            "skillbar": (440, 660, 840, 720),
            "items": (200, 660, 440, 720),
            "hp": (0, 0, 1280, 80),
        }

    def custom_event_title(self, category, timestamp: float) -> str:
        labels = {
            "teamfight": f"团战 · {timestamp:.0f}s",
            "laning": f"对线细节 · {timestamp:.0f}s",
            "resource_control": f"资源决策 · {timestamp:.0f}s",
        }
        return labels.get(category.value, "")

    def enrich_summary(self, match, summary: str) -> str:
        return summary + "\n[MOBA规则引擎补充] 建议关注视野布控与团战站位衔接。"
