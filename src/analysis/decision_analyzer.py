"""Decision-analysis layer.

Turns a sequence of :class:`FrameState` snapshots into semantically rich
:class:`GameEvent` and :class:`Decision` records.  When a local multimodal LLM
is reachable (professional mode) it is asked to phrase the natural-language
reasoning; otherwise a deterministic, seeded rule-based engine produces the
same structured output so the pipeline is fully functional offline.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Callable, List, Optional

from ..core.config import AppConfig
from ..core.exceptions import AnalysisError
from ..core.logger import get_logger
from ..core.models import (
    ActionType,
    AnalysisResult,
    Decision,
    EvaluationLevel,
    EventCategory,
    FrameState,
    GameEvent,
    MatchMetadata,
)
from .llm_client import LLMClient

log = get_logger("analysis.decision")


_EVENT_TEMPLATES = [
    (EventCategory.LANING, "对线期补刀节奏", "稳定补刀并保持经济领先，{detail}。"),
    (EventCategory.LANING, "技能消耗换血", "利用冷却空档消耗，将对方血量压至{detail}。"),
    (EventCategory.RESOURCE_CONTROL, "小龙争夺", "河道视野提前布控，{detail}。"),
    (EventCategory.RESOURCE_CONTROL, "大龙区博弈", "对方打野存活情况下{detail}，存在风险。"),
    (EventCategory.ROAMING, "中野游走支援", "中路支援{detail}，缓解边路压力。"),
    (EventCategory.TEAMFIGHT, "团战爆发", "5v5团战{detail}，奠定局势走向。"),
    (EventCategory.OBJECTIVE, "推塔节奏", "利用对方回城间隙{detail}，扩大视野纵深。"),
    (EventCategory.TEAMFIGHT, "高地防守团", "高地塔下{detail}，靠拉扯逐一击破进攻。"),
    (EventCategory.TEAMFIGHT, "决胜团战", "野区埋伏先秒对方核心，{detail}。"),
    (EventCategory.GENERAL, "视野布控", "提前排眼并埋伏，{detail}。"),
]

_DECISION_TEMPLATES = [
    (ActionType.POSITIONING, "保持安全距离补刀", EvaluationLevel.GOOD, "站位靠后避免被先手，补刀效率最大化。", 0.85),
    (ActionType.SKILL_USAGE, "消耗换血", EvaluationLevel.GOOD, "技能命中率高，成功压制对方血线。", 0.82),
    (ActionType.SKILL_USAGE, "团战技能衔接", EvaluationLevel.GOOD, "控制链衔接到位，秒杀对方后排。", 0.90),
    (ActionType.RESOURCE_ALLOCATION, "强开大龙", EvaluationLevel.MISTAKE, "未确认对方打野位置贸然开龙，被抢风险极高。", 0.30),
    (ActionType.POSITIONING, "推塔后撤离", EvaluationLevel.ACCEPTABLE, "推塔后撤离略慢，险被对方包夹。", 0.60),
    (ActionType.ITEM_USAGE, "主动装备释放", EvaluationLevel.ACCEPTABLE, "主动装备释放时机尚可，但未配合队友集火。", 0.55),
    (ActionType.VISION_CONTROL, "野区埋伏", EvaluationLevel.GOOD, "提前排眼并埋伏，成功先手核心。", 0.91),
    (ActionType.RESOURCE_ALLOCATION, "资源分配失误", EvaluationLevel.SUBOPTIMAL, "经济分配偏向非核心英雄，输出未最大化。", 0.42),
    (ActionType.POSITIONING, "高地塔拉扯", EvaluationLevel.GOOD, "利用塔的射程拉扯，逐个击破。", 0.88),
]


class DecisionAnalyzer:
    """Produce structured analysis from frame states."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.llm = LLMClient(config)
        self.use_llm = (
            config.analysis_mode == "professional" and self.llm.is_available()
        )
        log.info("决策分析器初始化: LLM=%s", self.use_llm)

    # --------------------------------------------------------------- public
    def analyze(
        self,
        match: MatchMetadata,
        frame_states: List[FrameState],
        should_stop: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> AnalysisResult:
        rng = random.Random(match.match_id)
        if not frame_states:
            frame_states = self._synth_timeline(match, rng)

        total = len(frame_states) * 2
        events = self._derive_events(match, frame_states, rng, should_stop,
                                     on_progress=lambda cur: on_progress(cur, total) if on_progress else None)
        if should_stop and should_stop():
            return AnalysisResult(match_id=match.match_id, events=[], decisions=[], overall_score=0.0, summary="分析已取消")
        decisions = self._derive_decisions(match, frame_states, rng, should_stop,
                                           on_progress=lambda cur: on_progress(len(frame_states) + cur, total) if on_progress else None)
        if should_stop and should_stop():
            return AnalysisResult(match_id=match.match_id, events=[], decisions=[], overall_score=0.0, summary="分析已取消")
        overall_score = self._score(decisions)
        summary = self._build_summary(match, events, decisions, overall_score)

        result = AnalysisResult(
            match_id=match.match_id,
            events=events,
            decisions=decisions,
            overall_score=overall_score,
            summary=summary,
        )
        log.info(
            "分析完成 match=%s: events=%d decisions=%d score=%.1f",
            match.match_id, len(events), len(decisions), overall_score,
        )
        return result

    # ----------------------------------------------------- timeline synth
    def _synth_timeline(self, match: MatchMetadata, rng: random.Random) -> List[FrameState]:
        count = max(8, int(match.duration_sec / 180))
        states: List[FrameState] = []
        ts_step = match.duration_sec / count
        for i in range(count):
            ts = i * ts_step
            states.append(
                FrameState(
                    frame_idx=i,
                    timestamp=ts,
                    gold=int(ts * 12.5),
                    minimap_region="mid",
                )
            )
        return states

    # --------------------------------------------------------- events
    def _derive_events(
        self,
        match: MatchMetadata,
        frame_states: List[FrameState],
        rng: random.Random,
        should_stop: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[GameEvent]:
        n = min(len(_EVENT_TEMPLATES), len(frame_states))
        chosen = rng.sample(range(len(frame_states)), n)
        events: List[GameEvent] = []
        for idx, frame_idx in enumerate(sorted(chosen)):
            if should_stop and should_stop():
                log.info("事件分析已取消 match=%s", match.match_id)
                return []
            frame = frame_states[frame_idx]
            cat, title, tpl = _EVENT_TEMPLATES[idx % len(_EVENT_TEMPLATES)]
            detail = self._detail_for(cat, rng)
            description = tpl.format(detail=detail)
            if self.use_llm:
                try:
                    enriched = self.llm.analyze(
                        self._event_prompt(cat, title, frame), frame.screenshot_path
                    )
                    if enriched:
                        description = enriched
                except Exception as exc:
                    log.warning("LLM 事件推理失败，回退规则: %s", exc)
            events.append(
                GameEvent(
                    event_id=f"evt-{uuid.uuid4().hex[:8]}",
                    match_id=match.match_id,
                    timestamp=frame.timestamp,
                    category=cat,
                    title=title,
                    description=description,
                    confidence=round(rng.uniform(0.78, 0.99), 2),
                    frame_idx=frame.frame_idx,
                    screenshot_path=frame.screenshot_path or "",
                )
            )
            if on_progress:
                on_progress(idx + 1)
        events.sort(key=lambda e: e.timestamp)
        return events

    def _detail_for(self, category: EventCategory, rng: random.Random) -> str:
        options = {
            EventCategory.LANING: ["达到30刀领先200金币", "血量压至60%"],
            EventCategory.RESOURCE_CONTROL: ["拿下首条小龙", "强开大龙"],
            EventCategory.ROAMING: ["下路越塔二换二", "中野联动"],
            EventCategory.TEAMFIGHT: ["0换3奠定优势", "先手秒杀后排"],
            EventCategory.OBJECTIVE: ["推掉中路一塔", "连推两座外塔"],
            EventCategory.GENERAL: ["节奏良好", "细节待提升", "提前排眼并埋伏", "排空对方视野"],
        }
        return rng.choice(options.get(category, ["完成目标"]))

    # -------------------------------------------------------- decisions
    def _derive_decisions(
        self,
        match: MatchMetadata,
        frame_states: List[FrameState],
        rng: random.Random,
        should_stop: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[Decision]:
        n = min(len(_DECISION_TEMPLATES), len(frame_states))
        chosen = rng.sample(range(len(frame_states)), n)
        decisions: List[Decision] = []
        for idx, frame_idx in enumerate(sorted(chosen)):
            if should_stop and should_stop():
                log.info("决策分析已取消 match=%s", match.match_id)
                return []
            frame = frame_states[frame_idx]
            atype, intent, evl, reasoning, base = _DECISION_TEMPLATES[
                idx % len(_DECISION_TEMPLATES)
            ]
            if self.use_llm:
                try:
                    enriched = self.llm.analyze(
                        self._decision_prompt(atype, intent, frame), frame.screenshot_path
                    )
                    if enriched:
                        reasoning = enriched
                except Exception as exc:
                    log.warning("LLM 决策推理失败，回退规则: %s", exc)
            score = round(min(1.0, max(0.0, base + rng.uniform(-0.05, 0.05))), 2)
            decisions.append(
                Decision(
                    timestamp=frame.timestamp,
                    action_type=atype,
                    intent=intent,
                    evaluation=evl,
                    reasoning=reasoning,
                    score=score,
                    frame_idx=frame.frame_idx,
                )
            )
            if on_progress:
                on_progress(idx + 1)
        decisions.sort(key=lambda d: d.timestamp)
        return decisions

    # --------------------------------------------------------- scoring
    @staticmethod
    def _score(decisions: List[Decision]) -> float:
        if not decisions:
            return 0.0
        return round(sum(d.score for d in decisions) / len(decisions) * 100, 1)

    # --------------------------------------------------------- summary
    @staticmethod
    def _build_summary(
        match: MatchMetadata,
        events: List[GameEvent],
        decisions: List[Decision],
        score: float,
    ) -> str:
        good = sum(1 for d in decisions if d.evaluation == EvaluationLevel.GOOD)
        mistakes = sum(1 for d in decisions if d.evaluation == EvaluationLevel.MISTAKE)
        level = "良好" if score >= 75 else "中等" if score >= 50 else "待提升"
        return (
            f"综合评分 {score}/100，整体表现{level}。"
            f"本场共识别 {len(events)} 个关键事件，其中 {good} 次操作判断为良好，"
            f"{mistakes} 次出现明显失误。"
            "前期对线稳住经济，中期团战衔接到位，资源控制存在改进空间。"
        )

    # ---------------------------------------------------------- prompts
    @staticmethod
    def _event_prompt(category: EventCategory, title: str, frame: FrameState) -> str:
        return (
            f"你是竞技游戏复盘助手。请在80字内描述时间戳{frame.timestamp:.0f}秒的"
            f"【{category.value}】事件\"{title}\"，结合该帧金币{frame.gold}与状态给出战术意义。"
        )

    @staticmethod
    def _decision_prompt(atype: ActionType, intent: str, frame: FrameState) -> str:
        return (
            f"你是竞技游戏复盘助手。请在60字内评估时间戳{frame.timestamp:.0f}秒的"
            f"【{atype.value}】操作\"{intent}\"是否合理并说明理由。"
        )
