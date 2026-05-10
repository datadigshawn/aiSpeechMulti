"""使用量 Ledger — 每次 STT/LLM 呼叫記一筆 event。

職責邊界：
- record(channel_id, engine, usage) → calc cost、寫 DB、更 in-memory cache
- today_total_twd() → SQL aggregate 今日總額（TST timezone）
- session_total_twd() → in-memory cache（process 啟動以來）
- by_channel() → 給 REST endpoint 拼 by_channel 列表用

不負責：
- 推 WebSocket（由 caller 在 record 後自己推）
- pricing JSON 載入（由 caller 注入 pricing dict，方便測試）
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.pricing import calc_cost, alert_level


@dataclass
class UsageEvent:
    """單一次模型使用紀錄。"""
    channel_id: str
    engine: str
    occurred_at: datetime
    usage: dict[str, int | float]
    cost_usd: float
    cost_twd: float


class UsageLedger:
    """In-memory + DB 雙寫的成本 ledger。

    v1 限制（Phase A 接受）：
    - _session_events list 無上限——server 跑數週後 by_channel() 會慢、占記憶體
      （v2: 改 running counters dict[tuple, float]）
    - today_total_twd / by_channel SQL 對 date() 函式無法走 idx_usage_occurred
      （Phase A scale ~100 rows/day 不痛；v2: GENERATED COLUMN date_local 加索引）
    - 不自設 PRAGMA journal_mode=WAL，依賴 app_api.py 在 startup 設好
      （v2: ledger __init__ 自設）
    """

    def __init__(self, db_path: Path, pricing: dict):
        """Args:
            db_path: SQLite DB 路徑（必須已套用 migration 0001 + 0002）
            pricing: pricing dict（utils.pricing.load_pricing() 的回傳值）
        """
        self.db_path = Path(db_path)
        self.pricing = pricing
        # in-memory cache：本次 server process 啟動以來所有 event（順序保留）
        self._session_events: list[UsageEvent] = []

    def record(
        self,
        channel_id: str,
        engine: str,
        usage: dict[str, int | float],
        occurred_at: datetime | None = None,
    ) -> UsageEvent:
        """記一筆使用 event：calc cost → 寫 DB → 加進 in-memory cache。

        Returns 寫入的 UsageEvent（caller 可拿來推 WebSocket）。
        """
        ts = occurred_at or datetime.now()
        cost_usd, cost_twd = calc_cost(engine, usage, self.pricing)
        event = UsageEvent(
            channel_id=channel_id,
            engine=engine,
            occurred_at=ts,
            usage=dict(usage),
            cost_usd=cost_usd,
            cost_twd=cost_twd,
        )

        # 寫 DB（同步；如未來嫌慢可包 asyncio.to_thread）
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO usage_log (channel_id, engine, occurred_at, usage_json, cost_usd, cost_twd)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel_id, engine, ts.isoformat(), json.dumps(usage), cost_usd, cost_twd),
            )
            conn.commit()
        finally:
            conn.close()

        self._session_events.append(event)
        return event

    def today_total_twd(self) -> float:
        """今日（TST = local time）總額。"""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_twd), 0.0) FROM usage_log
                WHERE date(occurred_at) = date('now', 'localtime')
                """
            ).fetchone()
            return float(row[0])
        finally:
            conn.close()

    def session_total_twd(self) -> float:
        """本次 process 啟動以來總額（in-memory）。"""
        return sum(e.cost_twd for e in self._session_events)

    def by_channel(self) -> list[dict]:
        """每席位的 today + session 細分，給 REST endpoint 用。

        Returns: list of dict, each:
            {
                "channel_id": "1",
                "today_twd": 18.20,
                "session_twd": 3.10,
                "by_engine": [
                    {"engine": "scribe_rt", "today_twd": 0.81, "session_twd": 0.20, "usage": {"audio_seconds": 237.0}},
                    ...
                ]
            }
        只回有資料的 channel；caller 自己決定要不要 pad 出 idle 的席位。
        """
        # SQL 拿今日 by channel × engine
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT channel_id, engine,
                       SUM(cost_twd)        AS twd,
                       SUM(json_extract(usage_json, '$.audio_seconds')) AS audio_seconds_sum
                FROM usage_log
                WHERE date(occurred_at) = date('now', 'localtime')
                GROUP BY channel_id, engine
                ORDER BY channel_id, engine
                """
            ).fetchall()
        finally:
            conn.close()

        # 整理成巢狀 by_channel 結構
        ch_map: dict[str, dict] = {}
        for ch_id, engine, twd, audio_sec in rows:
            ch = ch_map.setdefault(ch_id, {
                "channel_id": ch_id,
                "today_twd": 0.0,
                "session_twd": 0.0,
                "is_active": True,
                "by_engine": [],
            })
            ch["today_twd"] += float(twd or 0)
            ch["by_engine"].append({
                "engine": engine,
                "today_twd": float(twd or 0),
                "session_twd": sum(
                    e.cost_twd for e in self._session_events
                    if e.channel_id == ch_id and e.engine == engine
                ),
                "usage": {"audio_seconds": float(audio_sec or 0)} if audio_sec is not None else {},
            })

        # 補各 channel 的 session_twd
        for ch_id, ch in ch_map.items():
            ch["session_twd"] = sum(
                e.cost_twd for e in self._session_events if e.channel_id == ch_id
            )

        return list(ch_map.values())

    def alert_level(self) -> str:
        """目前 today_total 對應的警告等級。"""
        return alert_level(self.today_total_twd(), self.pricing)
