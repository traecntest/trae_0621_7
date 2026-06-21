"""Domain data models shared across all layers.

Every layer (presentation, business-logic, AI-analysis, persistence) operates
on the dataclasses defined here so that modules can be developed and tested in
isolation while remaining wire-compatible.  All models are plain data containers
with ``to_dict`` / ``from_dict`` helpers for SQLite/JSON serialization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AnalysisMode(str, Enum):
    """Granularity / fidelity of the analysis pipeline."""

    FAST = "fast"
    PROFESSIONAL = "professional"


class MatchStatus(str, Enum):
    """Lifecycle state of an imported recording."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventCategory(str, Enum):
    """Classification dimensions used by the report generator."""

    TEAMFIGHT = "teamfight"
    LANING = "laning"
    RESOURCE_CONTROL = "resource_control"
    OBJECTIVE = "objective"
    ROAMING = "roaming"
    GENERAL = "general"


class ActionType(str, Enum):
    """High-level action taxonomy used by the decision analyzer."""

    POSITIONING = "positioning"
    SKILL_USAGE = "skill_usage"
    ITEM_USAGE = "item_usage"
    RESOURCE_ALLOCATION = "resource_allocation"
    VISION_CONTROL = "vision_control"


class EvaluationLevel(str, Enum):
    """Qualitative verdict attached to a single decision."""

    GOOD = "good"
    ACCEPTABLE = "acceptable"
    SUBOPTIMAL = "suboptimal"
    MISTAKE = "mistake"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class HeroPosition:
    name: str
    team: str
    x: float
    y: float
    alive: bool = True
    hp_percent: float = 100.0


@dataclass
class SkillState:
    skill_name: str
    ready: bool
    cooldown_remaining: float = 0.0


@dataclass
class FrameState:
    """Structured snapshot of one decoded video frame."""

    frame_idx: int
    timestamp: float
    hero_positions: List[HeroPosition] = field(default_factory=list)
    skill_states: List[SkillState] = field(default_factory=list)
    items: List[str] = field(default_factory=list)
    hp_values: Dict[str, float] = field(default_factory=dict)
    gold: int = 0
    minimap_region: Optional[str] = None
    screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["hero_positions"] = [asdict(h) for h in self.hero_positions]
        data["skill_states"] = [asdict(s) for s in self.skill_states]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrameState":
        heroes = [HeroPosition(**h) for h in data.get("hero_positions", [])]
        skills = [SkillState(**s) for s in data.get("skill_states", [])]
        return cls(
            frame_idx=data["frame_idx"],
            timestamp=data["timestamp"],
            hero_positions=heroes,
            skill_states=skills,
            items=data.get("items", []),
            hp_values=data.get("hp_values", {}),
            gold=data.get("gold", 0),
            minimap_region=data.get("minimap_region"),
            screenshot_path=data.get("screenshot_path"),
        )


@dataclass
class GameEvent:
    """A discrete, timestamped occurrence detected during a match."""

    event_id: str
    match_id: str
    timestamp: float
    category: EventCategory
    title: str
    description: str
    confidence: float = 1.0
    frame_idx: int = 0
    screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameEvent":
        return cls(
            event_id=data["event_id"],
            match_id=data["match_id"],
            timestamp=data["timestamp"],
            category=EventCategory(data["category"]),
            title=data["title"],
            description=data["description"],
            confidence=data.get("confidence", 1.0),
            frame_idx=data.get("frame_idx", 0),
            screenshot_path=data.get("screenshot_path"),
        )


@dataclass
class Decision:
    """Intent + evaluation for a player action at a given timestamp."""

    timestamp: float
    action_type: ActionType
    intent: str
    evaluation: EvaluationLevel
    reasoning: str
    score: float = 0.0
    frame_idx: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action_type": self.action_type.value,
            "intent": self.intent,
            "evaluation": self.evaluation.value,
            "reasoning": self.reasoning,
            "score": self.score,
            "frame_idx": self.frame_idx,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Decision":
        return cls(
            timestamp=data["timestamp"],
            action_type=ActionType(data["action_type"]),
            intent=data["intent"],
            evaluation=EvaluationLevel(data["evaluation"]),
            reasoning=data["reasoning"],
            score=data.get("score", 0.0),
            frame_idx=data.get("frame_idx", 0),
        )


@dataclass
class MatchMetadata:
    """Top-level information about an imported recording."""

    match_id: str
    game_name: str
    player_name: str
    source_path: str
    duration_sec: float
    import_time: str = field(default_factory=_now_iso)
    analysis_mode: AnalysisMode = AnalysisMode.PROFESSIONAL
    status: MatchStatus = MatchStatus.PENDING
    progress: float = 0.0
    report_path: Optional[str] = None
    overall_score: Optional[float] = None
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "game_name": self.game_name,
            "player_name": self.player_name,
            "source_path": self.source_path,
            "duration_sec": self.duration_sec,
            "import_time": self.import_time,
            "analysis_mode": self.analysis_mode.value,
            "status": self.status.value,
            "progress": self.progress,
            "report_path": self.report_path,
            "overall_score": self.overall_score,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchMetadata":
        return cls(
            match_id=data["match_id"],
            game_name=data["game_name"],
            player_name=data["player_name"],
            source_path=data["source_path"],
            duration_sec=data["duration_sec"],
            import_time=data["import_time"],
            analysis_mode=AnalysisMode(data["analysis_mode"]),
            status=MatchStatus(data["status"]),
            progress=data.get("progress", 0.0),
            report_path=data.get("report_path"),
            overall_score=data.get("overall_score"),
            summary=data.get("summary"),
        )


@dataclass
class AnalysisResult:
    """Aggregate output of the AI-analysis pipeline for one match."""

    match_id: str
    events: List[GameEvent]
    decisions: List[Decision]
    overall_score: float
    summary: str
    generated_at: str = field(default_factory=_now_iso)


@dataclass
class ReportSection:
    """A grouped, time-ordered slice of the final report."""

    title: str
    category: EventCategory
    summary: str
    events: List[GameEvent] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
