"""SQLite-backed data persistence layer.

The :class:`Database` class owns the connection, schema creation and all
DAO operations.  Analysis results are stored both in structured tables (for
fast timeline queries) and as JSON payloads (for full-fidelity reload).
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .exceptions import DatabaseError
from .logger import get_logger
from .models import (
    AnalysisMode,
    Decision,
    EventCategory,
    GameEvent,
    MatchMetadata,
    MatchStatus,
)

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id      TEXT PRIMARY KEY,
    game_name     TEXT NOT NULL,
    player_name   TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    duration_sec  REAL NOT NULL,
    import_time   TEXT NOT NULL,
    analysis_mode TEXT NOT NULL,
    status        TEXT NOT NULL,
    progress      REAL NOT NULL DEFAULT 0,
    report_path   TEXT,
    overall_score REAL,
    summary       TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    match_id        TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    frame_idx       INTEGER NOT NULL DEFAULT 0,
    screenshot_path TEXT,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    action_type TEXT NOT NULL,
    intent      TEXT NOT NULL,
    evaluation  TEXT NOT NULL,
    reasoning   TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 0,
    frame_idx   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS frame_states (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   TEXT NOT NULL,
    frame_idx  INTEGER NOT NULL,
    timestamp  REAL NOT NULL,
    payload    TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key  TEXT PRIMARY KEY,
    match_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);
"""


class Database:
    """Thin SQLite wrapper with domain-specific DAO methods."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.connect()

    # ----------------------------------------------------------- connection
    def connect(self) -> None:
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"无法打开数据库 {self.db_path}: {exc}") from exc

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    # ------------------------------------------------------------- matches
    def upsert_match(self, match: MatchMetadata) -> None:
        d = match.to_dict()
        self.conn.execute(
            """
            INSERT INTO matches (match_id, game_name, player_name, source_path,
                                 duration_sec, import_time, analysis_mode, status,
                                 progress, report_path, overall_score, summary)
            VALUES (:match_id, :game_name, :player_name, :source_path,
                    :duration_sec, :import_time, :analysis_mode, :status,
                    :progress, :report_path, :overall_score, :summary)
            ON CONFLICT(match_id) DO UPDATE SET
                status=excluded.status,
                progress=excluded.progress,
                report_path=excluded.report_path,
                overall_score=excluded.overall_score,
                summary=excluded.summary
            """,
            d,
        )
        self.conn.commit()

    def get_match(self, match_id: str) -> Optional[MatchMetadata]:
        row = self.conn.execute(
            "SELECT * FROM matches WHERE match_id=?", (match_id,)
        ).fetchone()
        if not row:
            return None
        return MatchMetadata.from_dict(dict(row))

    def list_matches(self) -> List[MatchMetadata]:
        rows = self.conn.execute(
            "SELECT * FROM matches ORDER BY import_time DESC"
        ).fetchall()
        return [MatchMetadata.from_dict(dict(r)) for r in rows]

    def delete_match(self, match_id: str) -> None:
        self.conn.execute("DELETE FROM matches WHERE match_id=?", (match_id,))
        self.conn.execute("DELETE FROM events WHERE match_id=?", (match_id,))
        self.conn.execute("DELETE FROM decisions WHERE match_id=?", (match_id,))
        self.conn.execute("DELETE FROM frame_states WHERE match_id=?", (match_id,))
        self.conn.commit()

    # -------------------------------------------------------------- events
    def insert_event(self, event: GameEvent) -> None:
        d = event.to_dict()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO events (event_id, match_id, timestamp, category,
                                           title, description, confidence,
                                           frame_idx, screenshot_path)
            VALUES (:event_id, :match_id, :timestamp, :category, :title,
                    :description, :confidence, :frame_idx, :screenshot_path)
            """,
            d,
        )
        self.conn.commit()

    def get_events(self, match_id: str) -> List[GameEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE match_id=? ORDER BY timestamp", (match_id,)
        ).fetchall()
        return [GameEvent.from_dict(dict(r)) for r in rows]

    # ----------------------------------------------------------- decisions
    def insert_decision(self, match_id: str, decision: Decision) -> None:
        d = decision.to_dict()
        d["match_id"] = match_id
        self.conn.execute(
            """
            INSERT INTO decisions (match_id, timestamp, action_type, intent,
                                   evaluation, reasoning, score, frame_idx)
            VALUES (:match_id, :timestamp, :action_type, :intent, :evaluation,
                    :reasoning, :score, :frame_idx)
            """,
            d,
        )
        self.conn.commit()

    def get_decisions(self, match_id: str) -> List[Decision]:
        rows = self.conn.execute(
            "SELECT * FROM decisions WHERE match_id=? ORDER BY timestamp",
            (match_id,),
        ).fetchall()
        return [Decision.from_dict(dict(r)) for r in rows]

    # --------------------------------------------------------- frame states
    def insert_frame_state(self, match_id: str, payload: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO frame_states (match_id, frame_idx, timestamp, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                match_id,
                payload["frame_idx"],
                payload["timestamp"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def get_frame_states(self, match_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload FROM frame_states WHERE match_id=? ORDER BY frame_idx",
            (match_id,),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    # --------------------------------------------------------------- cache
    def get_cached(self, cache_key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT payload FROM analysis_cache WHERE cache_key=?", (cache_key,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def set_cached(self, cache_key: str, match_id: str, payload: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO analysis_cache (cache_key, match_id, created_at, payload) "
            "VALUES (?, ?, ?, ?)",
            (cache_key, match_id, datetime.now().isoformat(timespec="seconds"),
             json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def clear_cache(self) -> int:
        cur = self.conn.execute("DELETE FROM analysis_cache")
        self.conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Test-data initialisation
# ---------------------------------------------------------------------------
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def init_test_data(db: Database) -> MatchMetadata:
    """Seed the database with a representative MOBA sample match.

    The fixture covers every event category and evaluation level so that the
    GUI, timeline and report generator have realistic content to render
    without requiring an actual recording or model inference.
    """
    match = MatchMetadata(
        match_id=_new_id("match"),
        game_name="竞技对决：星耀峡谷",
        player_name="ShadowBlade",
        source_path="<test-data>/demo_replay.mp4",
        duration_sec=1830.0,
        analysis_mode=AnalysisMode.PROFESSIONAL,
        status=MatchStatus.DONE,
        progress=1.0,
        report_path="",
        overall_score=78.5,
        summary=(
            "前期对线稳住经济，10分钟小龙团战中技能衔接到位；中期资源控制存在一次决策失误，"
            "导致大龙被抢；后期团战站位偏后，依靠前排开团完成翻盘。整体节奏良好，细节仍有提升空间。"
        ),
    )
    db.upsert_match(match)

    # ---- events (timestamp, category, ...) --------------------------------
    sample_events = [
        (45.0, EventCategory.LANING, "对线期补刀节奏", "上线后保持稳定补刀，3分钟达到30刀，经济领先对手200金币。", 0.92, 90),
        (180.0, EventCategory.LANING, "技能消耗换血", "利用冷却空档用远程技能消耗，将对方血量压至60%。", 0.88, 360),
        (312.0, EventCategory.RESOURCE_CONTROL, "首轮小龙争夺", "河道视野提前布控，配合打野拿下第一条小龙。", 0.95, 624),
        (420.0, EventCategory.ROAMING, "中野游走下路", "中路支援下路越塔，完成二换二，缓解下路压力。", 0.81, 840),
        (612.0, EventCategory.TEAMFIGHT, "小龙团战爆发", "5v5团战先手开团，技能衔接流畅，0换3奠定优势。", 0.97, 1224),
        (780.0, EventCategory.RESOURCE_CONTROL, "大龙区误判", "对方打野存活情况下强开大龙，被抢龙并丢掉两个人头。", 0.79, 1560),
        (960.0, EventCategory.OBJECTIVE, "推塔节奏", "利用对方回城间隙推掉中路一塔，扩大视野纵深。", 0.90, 1920),
        (1180.0, EventCategory.TEAMFIGHT, "高地防守团", "高地塔下4v5防守，靠走位拉扯逐一击破对方进攻。", 0.86, 2360),
        (1420.0, EventCategory.TEAMFIGHT, "决胜团战", "野区埋伏先秒对方核心输出，顺势推平水晶。", 0.99, 2840),
    ]
    for ts, cat, title, desc, conf, fidx in sample_events:
        event = GameEvent(
            event_id=_new_id("evt"),
            match_id=match.match_id,
            timestamp=ts,
            category=cat,
            title=title,
            description=desc,
            confidence=conf,
            frame_idx=fidx,
            screenshot_path="",
        )
        db.insert_event(event)

    # ---- decisions --------------------------------------------------------
    from .models import ActionType, EvaluationLevel

    sample_decisions = [
        (45.0, ActionType.POSITIONING, "保持安全距离补刀", EvaluationLevel.GOOD, "站位靠后避免被先手，补刀效率最大化。", 0.85, 90),
        (180.0, ActionType.SKILL_USAGE, "消耗换血", EvaluationLevel.GOOD, "技能命中率高，成功压制对方血线。", 0.82, 360),
        (612.0, ActionType.SKILL_USAGE, "团战技能衔接", EvaluationLevel.GOOD, "控制链衔接到位，秒杀对方后排。", 0.90, 1224),
        (780.0, ActionType.RESOURCE_ALLOCATION, "强开大龙", EvaluationLevel.MISTAKE, "未确认对方打野位置贸然开龙，被抢风险极高。", 0.30, 1560),
        (960.0, ActionType.POSITIONING, "推塔后撤离", EvaluationLevel.ACCEPTABLE, "推塔后撤离略慢，险被对方包夹。", 0.60, 1920),
        (1180.0, ActionType.POSITIONING, "高地塔拉扯", EvaluationLevel.GOOD, "利用塔的射程拉扯，逐个击破。", 0.88, 2360),
        (1420.0, ActionType.VISION_CONTROL, "野区埋伏", EvaluationLevel.GOOD, "提前排眼并埋伏，成功先手核心。", 0.91, 2840),
    ]
    for ts, atype, intent, evl, reasoning, score, fidx in sample_decisions:
        db.insert_decision(
            match.match_id,
            Decision(
                timestamp=ts,
                action_type=atype,
                intent=intent,
                evaluation=evl,
                reasoning=reasoning,
                score=score,
                frame_idx=fidx,
            ),
        )

    log.info("测试数据已初始化: match_id=%s", match.match_id)
    return match
