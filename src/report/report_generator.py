"""HTML review-report generator for competitive replay analysis.

The :class:`ReportGenerator` turns the structured analysis output (events +
decisions) into a self-contained, time-ordered HTML document organised by
:class:`EventCategory`.  CSS is inlined so the report can be shared as a single
file; screenshots are base64-embedded when available.
"""

from __future__ import annotations

import base64
import html
import os
from datetime import datetime
from typing import Dict, List

from ..core.config import AppConfig
from ..core.exceptions import ReportGenerationError
from ..core.logger import get_logger
from ..core.models import (
    ActionType,
    Decision,
    EventCategory,
    EvaluationLevel,
    GameEvent,
    MatchMetadata,
    ReportSection,
)

log = get_logger("report")

_CATEGORY_LABELS: Dict[EventCategory, str] = {
    EventCategory.TEAMFIGHT: "团战",
    EventCategory.LANING: "对线",
    EventCategory.RESOURCE_CONTROL: "资源控制",
    EventCategory.OBJECTIVE: "目标",
    EventCategory.ROAMING: "游走",
    EventCategory.GENERAL: "通用",
}

_CATEGORY_ORDER: List[EventCategory] = [
    EventCategory.TEAMFIGHT,
    EventCategory.LANING,
    EventCategory.RESOURCE_CONTROL,
    EventCategory.OBJECTIVE,
    EventCategory.ROAMING,
    EventCategory.GENERAL,
]

_EVAL_LABELS: Dict[EvaluationLevel, str] = {
    EvaluationLevel.GOOD: "良好",
    EvaluationLevel.ACCEPTABLE: "可接受",
    EvaluationLevel.SUBOPTIMAL: "次优",
    EvaluationLevel.MISTAKE: "失误",
}

_EVAL_COLORS: Dict[EvaluationLevel, str] = {
    EvaluationLevel.GOOD: "#2e7d32",
    EvaluationLevel.ACCEPTABLE: "#1565c0",
    EvaluationLevel.SUBOPTIMAL: "#ef6c00",
    EvaluationLevel.MISTAKE: "#c62828",
}

_ACTION_LABELS: Dict[ActionType, str] = {
    ActionType.POSITIONING: "站位",
    ActionType.SKILL_USAGE: "技能使用",
    ActionType.ITEM_USAGE: "装备使用",
    ActionType.RESOURCE_ALLOCATION: "资源分配",
    ActionType.VISION_CONTROL: "视野控制",
}

_IMAGE_MIME = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "bmp": "bmp",
}


class ReportGenerator:
    """Assemble an :class:`AnalysisResult` into a standalone HTML report."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.log = get_logger("report")

    # ----------------------------------------------------------------- utils
    def format_timestamp(self, seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"

    def build_sections(
        self,
        events: List[GameEvent],
        decisions: List[Decision],
    ) -> List[ReportSection]:
        grouped: Dict[EventCategory, List[GameEvent]] = {}
        for event in events:
            grouped.setdefault(event.category, []).append(event)

        section_decisions: Dict[EventCategory, List[Decision]] = {
            category: [] for category in grouped
        }
        if events:
            for decision in decisions:
                nearest = min(
                    events,
                    key=lambda e: abs(e.timestamp - decision.timestamp),
                )
                section_decisions.setdefault(nearest.category, []).append(decision)

        sections: List[ReportSection] = []
        for category in _CATEGORY_ORDER:
            if category not in grouped:
                continue
            ordered_events = sorted(grouped[category], key=lambda e: e.timestamp)
            ordered_decisions = sorted(
                section_decisions.get(category, []),
                key=lambda d: d.timestamp,
            )
            sections.append(
                ReportSection(
                    title=_CATEGORY_LABELS[category],
                    category=category,
                    summary=(
                        f"共 {len(ordered_events)} 个事件，"
                        f"{len(ordered_decisions)} 个决策"
                    ),
                    events=ordered_events,
                    decisions=ordered_decisions,
                )
            )
        return sections

    # --------------------------------------------------------------- generate
    def generate(
        self,
        match: MatchMetadata,
        events: List[GameEvent],
        decisions: List[Decision],
    ) -> str:
        try:
            sections = self.build_sections(events, decisions)
            document = self._render(match, events, decisions, sections)
            os.makedirs(self.config.reports_dir, exist_ok=True)
            target = os.path.join(self.config.reports_dir, f"{match.match_id}.html")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(document)
            absolute = os.path.abspath(target)
            self.log.info("复盘报告已生成: %s", absolute)
            return absolute
        except ReportGenerationError:
            raise
        except Exception as exc:
            self.log.error("复盘报告生成失败: %s", exc)
            raise ReportGenerationError(f"复盘报告生成失败: {exc}") from exc

    # --------------------------------------------------------------- render
    def _render(
        self,
        match: MatchMetadata,
        events: List[GameEvent],
        decisions: List[Decision],
        sections: List[ReportSection],
    ) -> str:
        return (
            "<!DOCTYPE html>\n"
            '<html lang="zh-CN">\n<head>\n'
            '<meta charset="utf-8">\n'
            f"<title>复盘报告 - {self._escape(match.game_name)}</title>\n"
            f"<style>{self._css()}</style>\n"
            "</head>\n<body>\n"
            f"{self._render_header(match)}"
            f"{self._render_timeline(events)}"
            f"{self._render_sections(sections)}"
            f"{self._render_decision_table(decisions)}"
            f"{self._render_footer()}"
            "</body>\n</html>\n"
        )

    def _render_header(self, match: MatchMetadata) -> str:
        score = match.overall_score
        score_text = f"{score:.1f}" if score is not None else "未评分"
        info = [
            ("对局编号", match.match_id),
            ("游戏", match.game_name),
            ("玩家", match.player_name),
            ("时长", self.format_timestamp(match.duration_sec)),
            ("分析模式", match.analysis_mode.value),
            ("状态", match.status.value),
        ]
        rows = "".join(
            '<div class="info-item">'
            f'<span class="info-label">{self._escape(label)}</span>'
            f'<span class="info-value">{self._escape(value)}</span>'
            "</div>"
            for label, value in info
        )
        summary = ""
        if match.summary:
            summary = (
                f'<p class="summary">{self._escape(match.summary)}</p>'
            )
        return (
            '<header class="report-header">\n'
            "<h1>竞技复盘分析报告</h1>\n"
            '<div class="score-box">综合评分<br>'
            f'<span class="score-value">{score_text}</span></div>\n'
            f'<div class="info-grid">{rows}</div>\n'
            f"{summary}\n"
            "</header>\n"
        )

    def _render_timeline(self, events: List[GameEvent]) -> str:
        if not events:
            return (
                '<section class="timeline">\n<h2>时间轴</h2>'
                '<p class="empty">暂无事件</p>\n</section>\n'
            )
        ordered = sorted(events, key=lambda e: e.timestamp)
        items: List[str] = []
        for event in ordered:
            ts = self.format_timestamp(event.timestamp)
            badge = self._render_badge(event.category)
            items.append(
                '<div class="timeline-item">'
                f'<div class="timeline-time">{ts}</div>'
                '<div class="timeline-content">'
                f'<div class="timeline-head">{badge}'
                f'<span class="event-title">{self._escape(event.title)}</span></div>'
                f'<p class="event-desc">{self._escape(event.description)}</p>'
                f"{self._render_screenshot(event)}"
                "</div></div>\n"
            )
        return (
            '<section class="timeline">\n<h2>时间轴</h2>\n'
            f'<div class="timeline-list">{"".join(items)}</div>\n'
            "</section>\n"
        )

    def _render_sections(self, sections: List[ReportSection]) -> str:
        if not sections:
            return (
                '<section class="categories">\n<h2>分类分析</h2>'
                '<p class="empty">暂无分类数据</p>\n</section>\n'
            )
        parts: List[str] = ['<section class="categories">\n<h2>分类分析</h2>\n']
        for section in sections:
            parts.append(
                f'<div class="category-block" id="cat-{section.category.value}">\n'
                f"<h3>{self._escape(section.title)}"
                f'<span class="section-summary">{self._escape(section.summary)}</span></h3>\n'
            )
            parts.append('<div class="cat-events">\n')
            for event in section.events:
                ts = self.format_timestamp(event.timestamp)
                badge = self._render_badge(event.category)
                parts.append(
                    '<div class="cat-event">'
                    f'<span class="event-time">{ts}</span>{badge}'
                    '<div class="cat-event-body">'
                    f'<div class="event-title">{self._escape(event.title)}</div>'
                    f'<p class="event-desc">{self._escape(event.description)}</p>'
                    f"{self._render_screenshot(event)}"
                    "</div></div>\n"
                )
            parts.append("</div>\n")
            if section.decisions:
                parts.append(self._render_decision_table(section.decisions, full=False))
            parts.append("</div>\n")
        parts.append("</section>\n")
        return "".join(parts)

    def _render_decision_table(
        self, decisions: List[Decision], full: bool = True
    ) -> str:
        title = "决策总表" if full else "相关决策"
        if not decisions:
            return (
                f'<section class="decisions">\n<h2>{title}</h2>'
                '<p class="empty">暂无决策记录</p>\n</section>\n'
            )
        ordered = sorted(decisions, key=lambda d: d.timestamp)
        rows = "".join(self._render_decision_row(d) for d in ordered)
        tag = "section" if full else "div"
        return (
            f'<{tag} class="decisions">\n<h2>{title}</h2>\n'
            '<table class="decision-table">\n'
            "<thead><tr><th>时间</th><th>动作</th><th>意图</th>"
            "<th>评价</th><th>理由</th><th>得分</th></tr></thead>\n"
            f"<tbody>\n{rows}</tbody>\n</table>\n</{tag}>\n"
        )

    def _render_decision_row(self, decision: Decision) -> str:
        ts = self.format_timestamp(decision.timestamp)
        action = _ACTION_LABELS.get(
            decision.action_type, decision.action_type.value
        )
        eval_label = _EVAL_LABELS.get(
            decision.evaluation, decision.evaluation.value
        )
        color = _EVAL_COLORS.get(decision.evaluation, "#555555")
        return (
            "<tr>"
            f"<td>{ts}</td>"
            f"<td>{self._escape(action)}</td>"
            f"<td>{self._escape(decision.intent)}</td>"
            f'<td><span class="eval" style="color:{color};font-weight:bold">'
            f"{eval_label}</span></td>"
            f"<td>{self._escape(decision.reasoning)}</td>"
            f"<td>{decision.score:.2f}</td>"
            "</tr>\n"
        )

    def _render_badge(self, category: EventCategory) -> str:
        label = _CATEGORY_LABELS.get(category, category.value)
        return (
            f'<span class="badge badge-{category.value}">'
            f"{self._escape(label)}</span>"
        )

    def _render_screenshot(self, event: GameEvent) -> str:
        ts = self.format_timestamp(event.timestamp)
        path = event.screenshot_path
        if path and os.path.exists(path):
            try:
                uri = self._encode_image(path)
                return (
                    f'<img class="screenshot" src="{uri}" alt="{ts} 画面截图">'
                )
            except OSError:
                pass
        return (
            f'<div class="screenshot-placeholder">画面截图 · {ts}</div>'
        )

    def _encode_image(self, path: str) -> str:
        with open(path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode("ascii")
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = _IMAGE_MIME.get(ext, "png")
        return f"data:image/{mime};base64,{data}"

    def _render_footer(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f'<footer class="report-footer">报告生成时间：{now}</footer>\n'

    @staticmethod
    def _escape(text: object) -> str:
        return html.escape(str(text), quote=True)

    # ------------------------------------------------------------------- css
    @staticmethod
    def _css() -> str:
        return """
* { box-sizing: border-box; }
body {
    font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    margin: 0; padding: 0; background: #f5f6fa; color: #2c3e50; line-height: 1.6;
}
.report-header {
    background: linear-gradient(135deg, #1e3c72, #2a5298);
    color: #fff; padding: 28px 32px; position: relative;
}
.report-header h1 { margin: 0 0 12px 0; font-size: 26px; }
.score-box {
    position: absolute; top: 24px; right: 32px; text-align: center;
    background: rgba(255,255,255,0.15); padding: 12px 20px; border-radius: 10px; font-size: 13px;
}
.score-value { font-size: 30px; font-weight: bold; }
.info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 24px; max-width: 760px; }
.info-item { display: flex; flex-direction: column; }
.info-label { font-size: 12px; opacity: 0.75; }
.info-value { font-size: 15px; font-weight: 500; word-break: break-all; }
.summary {
    margin-top: 14px; max-width: 900px; background: rgba(255,255,255,0.12);
    padding: 12px 16px; border-radius: 8px;
}
section {
    background: #fff; margin: 18px auto; max-width: 1100px; padding: 20px 24px;
    border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
section h2 { margin-top: 0; border-left: 4px solid #2a5298; padding-left: 10px; }
.empty { color: #999; font-style: italic; }
.timeline-list { border-left: 2px solid #d0d7de; margin-left: 8px; padding-left: 16px; }
.timeline-item { display: flex; margin-bottom: 18px; position: relative; }
.timeline-time {
    width: 64px; flex-shrink: 0; font-weight: bold; color: #2a5298; padding-top: 2px;
}
.timeline-time::before {
    content: ""; position: absolute; left: -23px; top: 8px;
    width: 10px; height: 10px; border-radius: 50%; background: #2a5298; border: 2px solid #fff;
}
.timeline-content { flex: 1; }
.timeline-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.event-title { font-weight: 600; }
.event-desc { margin: 4px 0; color: #4a5568; }
.badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 12px; color: #fff; white-space: nowrap;
}
.badge-teamfight { background: #c62828; }
.badge-laning { background: #1565c0; }
.badge-resource_control { background: #2e7d32; }
.badge-objective { background: #6a1b9a; }
.badge-roaming { background: #ef6c00; }
.badge-general { background: #607d8b; }
.screenshot, .screenshot-placeholder {
    max-width: 480px; margin-top: 8px; border-radius: 6px; display: block;
}
.screenshot { border: 1px solid #e1e4e8; }
.screenshot-placeholder {
    background: #f0f2f5; border: 2px dashed #c2c7d0;
    padding: 24px; text-align: center; color: #8a94a6; font-size: 13px;
}
.categories .decisions { background: #fbfcfd; margin: 10px 0 0 0; box-shadow: none; padding: 12px 0; }
.category-block {
    border: 1px solid #eaecef; border-radius: 8px; padding: 14px 18px; margin-bottom: 16px;
}
.category-block h3 {
    margin-top: 0; color: #1e3c72; display: flex; align-items: center; gap: 12px;
}
.section-summary { font-size: 13px; color: #8a94a6; font-weight: normal; }
.cat-events { margin-bottom: 12px; }
.cat-event { padding: 8px 0; border-bottom: 1px dashed #eee; }
.cat-event .event-time { font-weight: bold; color: #2a5298; margin-right: 8px; }
.cat-event-body { margin-top: 4px; }
.decision-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }
.decision-table th, .decision-table td {
    border: 1px solid #e1e4e8; padding: 8px 10px; text-align: left;
}
.decision-table th { background: #f6f8fa; }
.decision-table tbody tr:nth-child(even) { background: #fafbfc; }
.report-footer { text-align: center; color: #8a94a6; padding: 24px; font-size: 13px; }
"""
