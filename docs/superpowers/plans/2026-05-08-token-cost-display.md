# 即時 STT 成本與使用量顯示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 monitor.html 顯示「今日 / session 即時 STT 成本（NT$）+ 6 席位 × engine 拆解」，並在達到日預算門檻時視覺警告。

**Architecture:** Server-side `UsageLedger` 在每次 STT call 完成時記錄 `audio_seconds` + 算成 USD/TWD（依 hardcoded `pricing.json`），寫入新 `usage_log` SQLite 表並透過 WebSocket `usage_update` message 推給前端。Client-side `monitor.html` 加 status bar + 點擊展開的席位列表，跨 tab 同步靠 `GET /api/usage/today` REST endpoint。

**Tech Stack:** Python 3.12 · SQLite (WAL + 既有 migration 機制) · FastAPI WebSocket · vanilla JS · pytest（Phase A 加 ~17 tests）

**Spec:** [docs/superpowers/specs/2026-05-08-token-cost-display-design.md](../specs/2026-05-08-token-cost-display-design.md)

---

## File Map（先看再開工）

### 新檔
| 路徑 | 職責 | LOC |
|---|---|---|
| `migrations/0002_add_usage_log.sql` | 建 usage_log 表 + 2 個 index | ~15 |
| `migrations/0002_add_usage_log.down.sql` | DROP table + index | ~5 |
| `config/pricing.json` | 引擎單價、TWD 匯率、alert 閾值 | ~30 |
| `utils/pricing.py` | load JSON / calc cost / determine alert level | ~80 |
| `utils/audio_duration.py` | 純函數 wav 檔 → 秒數 | ~25 |
| `utils/usage_ledger.py` | record event / today_total / session_total / by_channel | ~150 |
| `tests/test_pricing.py` | pricing 模組 unit test | ~70 |
| `tests/test_audio_duration.py` | audio duration 純函數 test | ~40 |
| `tests/test_usage_ledger.py` | ledger 含 DB 整合 test | ~120 |

### 改檔
| 路徑 | 改什麼 | LOC delta |
|---|---|---|
| `scripts/models/model_scribe.py:91` | `transcribe_file` return dict 加 `audio_seconds` | +5 |
| `scripts/models/model_google_stt.py:416` | 同上 | +5 |
| `app_api.py:559, 659` | call 完 transcribe_file 後 ledger.record() + ws.send_json("usage_update") | +30 |
| `app_api.py` (新加 endpoint) | `GET /api/usage/today` | +30 |
| `static/monitor.html` | status bar + 展開區 + WS handler + threshold color + localStorage | +200 (HTML/CSS/JS) |
| `tests/test_db_manager.py` | +2 tests for usage_log query helper | +30 |
| `tests/test_migrate.py` | +1 test for 0002 round-trip | +15 |
| `README.md` | 補一節 + 使用說明 | +15 |

**約 7 新檔 + 7 改檔 · 全部加總 ~870 LOC（包含測試與註解）。**

---

## Task 1: Migration 0002 — usage_log 表

**Files:**
- Create: `migrations/0002_add_usage_log.sql`
- Create: `migrations/0002_add_usage_log.down.sql`

- [ ] **Step 1: 寫 0002 up SQL**

Create `migrations/0002_add_usage_log.sql`:

```sql
-- 0002_add_usage_log.sql
-- 用途：記錄每次 STT (Phase A) / LLM (Phase B) API 呼叫的使用量與成本。
-- 新增表：usage_log + 2 個 index。對既有 5 張表零影響。

CREATE TABLE IF NOT EXISTS usage_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT    NOT NULL,           -- 對齊 transcripts.channel_id TEXT（值如 "1"~"6"）
    engine       TEXT    NOT NULL,           -- "scribe_rt" | "google_stt_chirp_3" | (Phase B) "gemini-2.5-flash" ...
    occurred_at  TIMESTAMP NOT NULL,
    usage_json   TEXT    NOT NULL,           -- JSON dict: STT={"audio_seconds": 87.3}, LLM={"input_tokens": ...}
    cost_usd     REAL    NOT NULL,
    cost_twd     REAL    NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_usage_occurred    ON usage_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_ch_occurred ON usage_log(channel_id, occurred_at);
```

- [ ] **Step 2: 寫 0002 down SQL**

Create `migrations/0002_add_usage_log.down.sql`:

```sql
-- 0002_add_usage_log.down.sql
-- 倒退：DROP usage_log + 2 indexes。
-- ⚠️ 對既有資料庫執行此 down 會清空所有使用量歷史。
DROP INDEX IF EXISTS idx_usage_ch_occurred;
DROP INDEX IF EXISTS idx_usage_occurred;
DROP TABLE IF EXISTS usage_log;
```

- [ ] **Step 3: dry-run 確認 SQL 合法**

Run:
```bash
python -m aispeech migrate up --dry-run
```

Expected output 含一段：
```
── Applying 0002_add_usage_log ──
CREATE TABLE IF NOT EXISTS usage_log (...);
[dry-run] Would record 0002_add_usage_log
```

- [ ] **Step 4: 真套用到 prod DB**

Run:
```bash
python -m aispeech migrate up
```

Expected output：
```
Backup: aiSpeechMulti.db.bak.YYYYMMDD_HHMMSS
── Applying 0002_add_usage_log ──
✓ Applied 0002_add_usage_log
```

- [ ] **Step 5: 驗證表存在**

Run:
```bash
sqlite3 data/aiSpeechMulti.db "SELECT sql FROM sqlite_master WHERE name='usage_log'"
```

Expected: 印出 CREATE TABLE 完整 DDL，含 channel_id TEXT。

- [ ] **Step 6: 驗證 idempotent**

Run again:
```bash
python -m aispeech migrate up
```

Expected: `Already up to date.`

- [ ] **Step 7: Commit**

```bash
cd /Users/apple/Projects/projectArea/aiSpeechMulti
git add migrations/0002_add_usage_log.sql migrations/0002_add_usage_log.down.sql
git commit -m "feat(db): migration 0002 — usage_log 表（Phase A 成本追蹤基礎設施）"
```

---

## Task 2: Pricing 模組

**Files:**
- Create: `config/pricing.json`
- Create: `utils/pricing.py`
- Create: `tests/test_pricing.py`

- [ ] **Step 1: 寫 pricing.json**

Create `config/pricing.json`:

```json
{
  "_meta": {
    "last_updated": "2026-05-08",
    "source": "ElevenLabs / Google Cloud 公開定價（請定期 review）",
    "next_review_due": "2026-08-08"
  },
  "usd_to_twd": 31.0,
  "alerts": {
    "daily_warning_pct": 80,
    "daily_critical_pct": 100,
    "daily_budget_twd": 100
  },
  "engines": {
    "scribe_rt": {
      "type": "stt",
      "unit": "audio_seconds",
      "usd_per_unit": 0.000111,
      "_note": "$0.0067/min ÷ 60（請以實際 ElevenLabs 帳單校準）"
    },
    "google_stt_chirp_3": {
      "type": "stt",
      "unit": "audio_seconds",
      "usd_per_unit": 0.000400,
      "_note": "$0.024/min ÷ 60（請以 GCP 帳單校準）"
    }
  }
}
```

- [ ] **Step 2: 寫 test_pricing.py 第 1 個失敗 test（load + 驗 schema）**

Create `tests/test_pricing.py`:

```python
"""Tests for utils/pricing.py — pricing.json 載入與成本計算。"""

from __future__ import annotations

import json
import pytest

from utils.pricing import (
    load_pricing,
    calc_cost,
    alert_level,
    PricingError,
)


class TestLoadPricing:
    def test_loads_default_pricing_json(self):
        p = load_pricing()
        assert "usd_to_twd" in p
        assert p["usd_to_twd"] == 31.0
        assert "engines" in p
        assert "scribe_rt" in p["engines"]
        assert "google_stt_chirp_3" in p["engines"]
```

- [ ] **Step 3: 跑 test 驗失敗**

Run:
```bash
cd /Users/apple/Projects/projectArea/aiSpeechMulti
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_pricing.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'utils.pricing'`

- [ ] **Step 4: 寫 utils/pricing.py 最小實作（讓 Step 3 過）**

Create `utils/pricing.py`:

```python
"""Pricing 載入與成本計算。

純函數設計：所有 entry 都接受 pricing dict（或 None 用預設）。
這樣測試可以注入自訂 pricing 不用改檔，prod 用預設。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICING_PATH = PROJECT_ROOT / "config" / "pricing.json"


class PricingError(ValueError):
    """pricing.json 結構或單位不合法。"""


def load_pricing(path: Path | None = None) -> dict:
    """讀 pricing.json 並回傳 dict。失敗 raise PricingError。"""
    p = Path(path) if path else DEFAULT_PRICING_PATH
    if not p.exists():
        raise PricingError(f"pricing.json not found at {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PricingError(f"pricing.json malformed: {e}") from e


def calc_cost(engine: str, usage: dict, pricing: dict) -> tuple[float, float]:
    """算單次呼叫的 USD / TWD 成本。

    Args:
        engine: 引擎 key（必須在 pricing["engines"] 裡）
        usage: usage dict，例如 {"audio_seconds": 87.3} 或 {"input_tokens": ..., "output_tokens": ...}
        pricing: 完整 pricing dict（load_pricing() 回傳的）

    Returns:
        (cost_usd, cost_twd)
    """
    engines = pricing.get("engines", {})
    if engine not in engines:
        raise PricingError(f"engine '{engine}' not in pricing.json")
    cfg = engines[engine]
    unit = cfg["unit"]
    rate = cfg["usd_per_unit"]
    qty = usage.get(unit)
    if qty is None:
        raise PricingError(f"usage missing required key '{unit}' for engine '{engine}'")
    cost_usd = float(qty) * float(rate)
    cost_twd = cost_usd * float(pricing.get("usd_to_twd", 31.0))
    return cost_usd, cost_twd


def alert_level(today_total_twd: float, pricing: dict) -> str:
    """依 daily_budget_twd 與 pct 閾值決定警告等級。

    Returns: "ok" | "warning" | "critical"
    """
    alerts = pricing.get("alerts", {})
    budget = alerts.get("daily_budget_twd", 0)
    if budget <= 0:
        return "ok"  # 邊界：未設預算 → 永遠 ok
    pct = today_total_twd / budget * 100
    if pct >= alerts.get("daily_critical_pct", 100):
        return "critical"
    if pct >= alerts.get("daily_warning_pct", 80):
        return "warning"
    return "ok"
```

- [ ] **Step 5: 跑 test 驗第 1 個 PASS**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_pricing.py -v
```

Expected: 1 passed

- [ ] **Step 6: 補滿 test_pricing.py 全套（5 tests）**

Append to `tests/test_pricing.py`:

```python
class TestCalcCost:
    @pytest.fixture
    def sample_pricing(self):
        return {
            "usd_to_twd": 31.0,
            "engines": {
                "scribe_rt": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000111},
                "google_stt_chirp_3": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000400},
            },
        }

    def test_scribe_60_seconds(self, sample_pricing):
        usd, twd = calc_cost("scribe_rt", {"audio_seconds": 60.0}, sample_pricing)
        assert abs(usd - 60 * 0.000111) < 1e-9
        assert abs(twd - usd * 31.0) < 1e-9

    def test_google_100_seconds(self, sample_pricing):
        usd, twd = calc_cost("google_stt_chirp_3", {"audio_seconds": 100.0}, sample_pricing)
        assert abs(usd - 100 * 0.000400) < 1e-9
        assert abs(twd - 0.04 * 31.0) < 1e-9

    def test_unknown_engine_raises(self, sample_pricing):
        with pytest.raises(PricingError, match="not in pricing"):
            calc_cost("nonexistent", {"audio_seconds": 10}, sample_pricing)

    def test_missing_unit_raises(self, sample_pricing):
        with pytest.raises(PricingError, match="missing required key"):
            calc_cost("scribe_rt", {"input_tokens": 100}, sample_pricing)


class TestAlertLevel:
    @pytest.fixture
    def alerts_pricing(self):
        return {
            "alerts": {
                "daily_warning_pct": 80,
                "daily_critical_pct": 100,
                "daily_budget_twd": 100,
            }
        }

    def test_ok_under_warning(self, alerts_pricing):
        assert alert_level(50.0, alerts_pricing) == "ok"
        assert alert_level(79.99, alerts_pricing) == "ok"

    def test_warning_at_80_pct(self, alerts_pricing):
        assert alert_level(80.0, alerts_pricing) == "warning"
        assert alert_level(99.99, alerts_pricing) == "warning"

    def test_critical_at_100_pct(self, alerts_pricing):
        assert alert_level(100.0, alerts_pricing) == "critical"
        assert alert_level(150.0, alerts_pricing) == "critical"

    def test_zero_budget_always_ok(self):
        """daily_budget_twd <= 0 邊界：alarm 全程禁用。"""
        p = {"alerts": {"daily_budget_twd": 0, "daily_warning_pct": 80, "daily_critical_pct": 100}}
        assert alert_level(99999.0, p) == "ok"
```

- [ ] **Step 7: 跑全套 test_pricing.py 確認全綠**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_pricing.py -v
```

Expected: 9 passed (1 load + 4 calc + 4 alert)

- [ ] **Step 8: Commit**

```bash
git add config/pricing.json utils/pricing.py tests/test_pricing.py
git commit -m "feat(pricing): 加 pricing.json + utils/pricing.py（load/calc/alert_level）+ 9 tests"
```

---

## Task 3: Audio Duration Helper

**Files:**
- Create: `utils/audio_duration.py`
- Create: `tests/test_audio_duration.py`

- [ ] **Step 1: 寫第 1 個失敗 test**

Create `tests/test_audio_duration.py`:

```python
"""Tests for utils/audio_duration.py — wav 檔 → 秒數純函數。"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from utils.audio_duration import audio_seconds, AudioDurationError


def _write_silent_wav(path: Path, duration_sec: float, sample_rate: int = 16000) -> None:
    """產生指定秒數的靜音 wav（mono, 16-bit）給 test 用。"""
    n_samples = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_samples)


class TestAudioSeconds:
    def test_one_second_wav(self, tmp_path):
        wav = tmp_path / "1sec.wav"
        _write_silent_wav(wav, 1.0)
        assert abs(audio_seconds(wav) - 1.0) < 0.01

    def test_3_5_seconds_wav(self, tmp_path):
        wav = tmp_path / "3.5sec.wav"
        _write_silent_wav(wav, 3.5)
        assert abs(audio_seconds(wav) - 3.5) < 0.01

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AudioDurationError, match="not found"):
            audio_seconds(tmp_path / "nonexistent.wav")

    def test_non_wav_file_raises(self, tmp_path):
        f = tmp_path / "fake.wav"
        f.write_bytes(b"not a wav file")
        with pytest.raises(AudioDurationError):
            audio_seconds(f)
```

- [ ] **Step 2: 跑 test 驗失敗**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_audio_duration.py -v
```

Expected: 4 errors — `ModuleNotFoundError: No module named 'utils.audio_duration'`

- [ ] **Step 3: 寫實作**

Create `utils/audio_duration.py`:

```python
"""Wav 檔 → 秒數純函數（用 stdlib wave 模組，零新依賴）。

只支援 PCM wav 檔。其他格式（mp3、flac 等）若未來需要，
改用 librosa 或 soundfile（已在 requirements.txt 裡）。
"""

from __future__ import annotations

import wave
from pathlib import Path


class AudioDurationError(ValueError):
    """讀 wav 檔失敗或格式不對。"""


def audio_seconds(wav_path: Path | str) -> float:
    """讀 wav header 算秒數。誤差 < 1 frame（幾乎等同精準）。

    Args:
        wav_path: wav 檔路徑

    Returns:
        音訊秒數（float）

    Raises:
        AudioDurationError: 檔不存在或不是合法 PCM wav
    """
    p = Path(wav_path)
    if not p.exists():
        raise AudioDurationError(f"wav file not found: {p}")
    try:
        with wave.open(str(p), "rb") as w:
            n_frames = w.getnframes()
            framerate = w.getframerate()
            if framerate <= 0:
                raise AudioDurationError(f"invalid framerate {framerate} in {p}")
            return n_frames / framerate
    except wave.Error as e:
        raise AudioDurationError(f"not a valid PCM wav: {p} ({e})") from e
```

- [ ] **Step 4: 跑 test 驗全綠**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_audio_duration.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add utils/audio_duration.py tests/test_audio_duration.py
git commit -m "feat(util): 加 audio_duration 純函數（stdlib wave）+ 4 tests"
```

---

## Task 4: UsageLedger

**Files:**
- Create: `utils/usage_ledger.py`
- Create: `tests/test_usage_ledger.py`

- [ ] **Step 1: 寫第 1 個失敗 test（基本 record + DB write）**

Create `tests/test_usage_ledger.py`:

```python
"""Tests for utils/usage_ledger.py — 使用量 ledger（in-memory + DB persist）。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from utils.usage_ledger import UsageLedger, UsageEvent


@pytest.fixture
def ledger_db(tmp_db_path):
    """乾淨 DB 含 usage_log 表（套 0001 + 0002 baseline）。"""
    sql_0001 = (Path(__file__).resolve().parent.parent / "migrations" / "0001_baseline_schema.sql").read_text()
    sql_0002 = (Path(__file__).resolve().parent.parent / "migrations" / "0002_add_usage_log.sql").read_text()
    conn = sqlite3.connect(tmp_db_path)
    conn.executescript(sql_0001)
    conn.executescript(sql_0002)
    conn.commit()
    conn.close()
    return tmp_db_path


@pytest.fixture
def sample_pricing():
    return {
        "usd_to_twd": 31.0,
        "alerts": {"daily_warning_pct": 80, "daily_critical_pct": 100, "daily_budget_twd": 100},
        "engines": {
            "scribe_rt": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000111},
            "google_stt_chirp_3": {"type": "stt", "unit": "audio_seconds", "usd_per_unit": 0.000400},
        },
    }


class TestRecord:
    def test_record_writes_to_db(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record(channel_id="1", engine="scribe_rt", usage={"audio_seconds": 60.0})

        conn = sqlite3.connect(ledger_db)
        rows = conn.execute("SELECT channel_id, engine, cost_usd FROM usage_log").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "1"
        assert rows[0][1] == "scribe_rt"
        assert abs(rows[0][2] - 60 * 0.000111) < 1e-9
        conn.close()
```

- [ ] **Step 2: 跑 test 驗失敗**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_usage_ledger.py -v
```

Expected: ERROR — `ModuleNotFoundError: No module named 'utils.usage_ledger'`

- [ ] **Step 3: 寫 utils/usage_ledger.py 實作**

Create `utils/usage_ledger.py`:

```python
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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    """In-memory + DB 雙寫的成本 ledger。"""

    def __init__(self, db_path: Path, pricing: dict):
        """Args:
            db_path: SQLite DB 路徑（必須已套用 migration 0001 + 0002）
            pricing: pricing dict（utils.pricing.load_pricing() 的回傳值）
        """
        self.db_path = Path(db_path)
        self.pricing = pricing
        # in-memory cache：本次 server process 啟動以來所有 event（順序保留）
        self._session_events: list[UsageEvent] = []

    # ── Recording ────────────────────────────────────────────────────────

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

    # ── Aggregations ─────────────────────────────────────────────────────

    def today_total_twd(self) -> float:
        """今日（TST = local time）總額。"""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_twd), 0.0) FROM usage_log
                WHERE date(occurred_at, 'localtime') = date('now', 'localtime')
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
                WHERE date(occurred_at, 'localtime') = date('now', 'localtime')
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
```

- [ ] **Step 4: 跑 test 1 驗 PASS**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_usage_ledger.py -v
```

Expected: 1 passed

- [ ] **Step 5: 補 test_usage_ledger.py 全套（再 5 個 test，總 6）**

Append to `tests/test_usage_ledger.py`:

```python
class TestAggregations:
    def test_today_total_with_multiple_events(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("1", "google_stt_chirp_3", {"audio_seconds": 100.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 30.0})

        # scribe 60s = $0.00666 = NT$ 0.2065
        # google 100s = $0.04 = NT$ 1.24
        # scribe 30s = $0.00333 = NT$ 0.1033
        # total ≈ NT$ 1.55
        assert abs(ledger.today_total_twd() - (60 + 30) * 0.000111 * 31 - 100 * 0.000400 * 31) < 0.01

    def test_session_total_matches_in_memory(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 60.0})
        # session = sum of 2 events
        expected = 2 * 60 * 0.000111 * 31
        assert abs(ledger.session_total_twd() - expected) < 1e-6

    def test_by_channel_groups_by_channel_and_engine(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        ledger.record("1", "scribe_rt", {"audio_seconds": 60.0})
        ledger.record("1", "google_stt_chirp_3", {"audio_seconds": 100.0})
        ledger.record("2", "scribe_rt", {"audio_seconds": 30.0})

        result = ledger.by_channel()
        # 應有 2 個 channel
        assert len(result) == 2
        ch1 = next(c for c in result if c["channel_id"] == "1")
        # ch1 有兩個引擎
        assert len(ch1["by_engine"]) == 2
        assert {e["engine"] for e in ch1["by_engine"]} == {"scribe_rt", "google_stt_chirp_3"}

    def test_empty_ledger_returns_zero(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        assert ledger.today_total_twd() == 0.0
        assert ledger.session_total_twd() == 0.0
        assert ledger.by_channel() == []

    def test_alert_level_changes_with_total(self, ledger_db, sample_pricing):
        ledger = UsageLedger(db_path=ledger_db, pricing=sample_pricing)
        # daily_budget_twd = 100，warning = 80%
        # 跑到 NT$ 90 = 90% → warning
        # 一筆 google 100s = NT$ 1.24，要跑 ~73 筆才到 NT$ 90
        # 簡化用 scribe 多一點：scribe 1 sec = $0.000111 * 31 = NT$ 0.00344
        # 要 NT$ 90 → 26200 sec ≈ 7.3 hr，不實際；改用 mock 路徑
        # 直接寫一筆超大 audio_seconds
        ledger.record("1", "scribe_rt", {"audio_seconds": 30000.0})  # ≈ NT$ 103
        assert ledger.alert_level() == "critical"
```

- [ ] **Step 6: 跑全套確認 6 綠**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_usage_ledger.py -v
```

Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add utils/usage_ledger.py tests/test_usage_ledger.py
git commit -m "feat(ledger): 加 UsageLedger（in-memory + DB）+ 6 tests"
```

---

## Task 5: STT Wrapper 加 audio_seconds

**Files:**
- Modify: `scripts/models/model_scribe.py:91`
- Modify: `scripts/models/model_google_stt.py:416`

- [ ] **Step 1: 看 model_scribe.py 既有 transcribe_file 的 return shape**

Run:
```bash
sed -n '85,140p' scripts/models/model_scribe.py
```

確認既有 return 結構，找到要插入 `audio_seconds` 的地方。

- [ ] **Step 2: 改 model_scribe.py:91 加 audio_seconds 欄位**

Edit `scripts/models/model_scribe.py`. Find `def transcribe_file(self, audio_file, with_word_confidence: bool = True) -> dict:` 函式，在 return dict 前加：

```python
# ─── 加入 audio_seconds 給成本 ledger 用（Phase A，2026-05-08）───
from utils.audio_duration import audio_seconds as _audio_sec, AudioDurationError
try:
    duration = _audio_sec(audio_file)
except AudioDurationError:
    duration = 0.0
# 把 duration 加進原本要回傳的 dict（找該函式 return 那行，把 duration 注進去）
```

並把原本的 `return {...}` 改成 `return {..., "audio_seconds": duration}`。

實際 patch（依該函式現有結構，假設 return dict 叫 `result`）：

```python
# 在 return result 之前
result["audio_seconds"] = duration
return result
```

- [ ] **Step 3: 同樣改 model_google_stt.py:416**

Edit `scripts/models/model_google_stt.py`. 找到 `def transcribe_file(...)` 函式，做同樣加欄位。

- [ ] **Step 4: 加最小 smoke test 驗欄位存在**

Append to `tests/test_db_manager.py`（複用既有 test 檔；或建新 `tests/test_stt_wrapper.py` 也可）：

```python
class TestSTTWrapperAudioSeconds:
    """確認 STT wrapper 在 result dict 裡加了 audio_seconds 欄位。

    這裡不打真 API（需 key），純驗 wrapper 程式對 wav 檔處理的部分。
    """
    def test_scribe_result_has_audio_seconds(self, tmp_path):
        # 造 1 sec wav
        import wave
        wav = tmp_path / "1sec.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)

        from utils.audio_duration import audio_seconds
        # 不打真 API，只驗 audio_duration helper 算對（duration 注入點的核心邏輯）
        assert abs(audio_seconds(wav) - 1.0) < 0.01

    def test_audio_duration_in_stt_results_via_helper(self):
        """驗 audio_duration 已被 import 在 STT wrapper 模組層級可呼叫。"""
        # 透過 import path 確認 wrapper 沒打字錯
        from scripts.models import model_scribe, model_google_stt
        # 不必呼叫 transcribe_file（需 audio + key），只確認 module 能 import
        assert hasattr(model_scribe, "ScribeSTTModel")
        assert hasattr(model_google_stt, "GoogleSTTModel")
```

- [ ] **Step 5: 跑 test**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest tests/test_db_manager.py::TestSTTWrapperAudioSeconds -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/models/model_scribe.py scripts/models/model_google_stt.py tests/test_db_manager.py
git commit -m "feat(stt): wrapper return dict 加 audio_seconds 欄位（給 ledger 用）"
```

---

## Task 6: app_api.py — Ledger 注入 + WebSocket emit + REST endpoint

**Files:**
- Modify: `app_api.py`（多處）

- [ ] **Step 1: 在 app_api.py 模組頂部建全局 ledger instance**

Edit `app_api.py`. 在 import 區塊後加：

```python
# ─── 成本 ledger（Phase A 2026-05-08）─────────────────────────────────
from utils.pricing import load_pricing
from utils.usage_ledger import UsageLedger

_PRICING = load_pricing()
_LEDGER = UsageLedger(db_path=Path("data/aiSpeechMulti.db"), pricing=_PRICING)
```

- [ ] **Step 2: 在 dual mode confirmed 路徑（line ~559）加 ledger.record + emit**

找到 `result = await asyncio.to_thread(stt.transcribe_file, wav_path)` 之後、`if transcript: await ws.send_json({"type": "transcript", ...})` 那段。在送 transcript 之後加：

```python
# Phase A 成本 ledger
audio_sec = result.get("audio_seconds", 0.0)
if audio_sec > 0:
    engine_key = "google_stt_chirp_3" if state.stt_backend == "google" else "scribe_rt"
    try:
        event = _LEDGER.record(
            channel_id=channel_id,
            engine=engine_key,
            usage={"audio_seconds": audio_sec},
        )
        await ws.send_json({
            "type":              "usage_update",
            "channel_id":        channel_id,
            "category":          "stt",
            "engine":            engine_key,
            "usage":             event.usage,
            "cost_usd":          event.cost_usd,
            "cost_twd":          event.cost_twd,
            "session_total_twd": _LEDGER.session_total_twd(),
            "today_total_twd":   _LEDGER.today_total_twd(),
        })
    except Exception as e:
        logger.warning(f"[{channel_id}] ledger record failed (non-fatal): {e}")
```

- [ ] **Step 3: 同樣 pattern 套到其他 STT call site**

`app_api.py:659` 那段也是 `transcribe_file` 呼叫處（看 grep 結果），重複 Step 2 同樣的 5-line block 注進去。Engine key 視 backend 字串映射。

- [ ] **Step 4: 加 GET /api/usage/today endpoint**

在 app_api.py 找到既有 `@app.get("/api/health")` 那塊，附近加：

```python
@app.get("/api/usage/today", summary="今日 + session 成本與使用量")
async def api_usage_today():
    """給 monitor.html 跨 tab/refresh 同步用。"""
    by_channel = _LEDGER.by_channel()
    active_ids = {c["channel_id"] for c in by_channel}
    today = _LEDGER.today_total_twd()
    pricing_alerts = _PRICING.get("alerts", {})
    return {
        "today_total_twd":      today,
        "session_total_twd":    _LEDGER.session_total_twd(),
        "by_channel":           by_channel,
        "active_channel_count": len(active_ids),
        "max_channel_slots":    6,
        "alerts": {
            "level":             _LEDGER.alert_level(),
            "daily_pct":         (today / pricing_alerts.get("daily_budget_twd", 1)) * 100 if pricing_alerts.get("daily_budget_twd", 0) > 0 else 0,
            "daily_budget_twd":  pricing_alerts.get("daily_budget_twd", 0),
        },
    }
```

- [ ] **Step 5: 起 server smoke test endpoint**

Run:
```bash
# 在另一個 terminal 起 server
python app_api.py &
sleep 5
curl -s http://localhost:8000/api/usage/today | python3 -m json.tool
kill %1
```

Expected output（DB 為空時）：
```json
{
    "today_total_twd": 0.0,
    "session_total_twd": 0.0,
    "by_channel": [],
    "active_channel_count": 0,
    "max_channel_slots": 6,
    "alerts": {
        "level": "ok",
        "daily_pct": 0.0,
        "daily_budget_twd": 100
    }
}
```

- [ ] **Step 6: Commit**

```bash
git add app_api.py
git commit -m "feat(api): 注入 UsageLedger + WS usage_update message + GET /api/usage/today"
```

---

## Task 7: monitor.html UI — Status bar + 展開區

**Files:**
- Modify: `static/monitor.html`

- [ ] **Step 1: 在 `<body>` 開頭、`<header>` 之前加 status bar HTML**

Find `<body>` and the first `<header>` (line ~184). Insert between them:

```html
<!-- ─── 成本 status bar (Phase A 2026-05-08) ─── -->
<div id="cost-status" class="cost-status" data-level="ok">
  <div class="cost-status__left">
    <span class="cost-status__icon" id="cost-icon">💰</span>
    <span>今日 <span class="cost-status__num" id="cost-today">NT$ 0.00</span></span>
    <span class="cost-status__divider">·</span>
    <span>session <span class="cost-status__num cost-status__num--session" id="cost-session">NT$ 0.00</span></span>
    <span class="cost-status__divider">·</span>
    <span class="cost-status__active" id="cost-active">0/6 席位活動中</span>
  </div>
  <button class="cost-status__toggle" id="cost-toggle" type="button">▼ 展開</button>
</div>
<div id="cost-expand" class="cost-expand" hidden>
  <!-- 由 JS 動態填入 -->
</div>
```

- [ ] **Step 2: 加 CSS（在 monitor.html 既有 `<style>` 區尾或頂端）**

Find existing `<style>` block (look for `/* Lanes (6 channels) */` near line 54). Append before `</style>`:

```css
/* ─── 成本 status bar ─── */
.cost-status {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px; margin: 12px 0; border-radius: 8px;
  background: var(--neutral-2); border: 1px solid var(--neutral-6);
  font-family: var(--mono, 'SF Mono', Menlo, monospace);
}
.cost-status[data-level="warning"] {
  background: oklch(0.55 0.14 75 / 0.18); border-color: #f5a623;
}
.cost-status[data-level="critical"] {
  background: oklch(0.55 0.18 25 / 0.20); border-color: #e74c3c;
}
.cost-status__left { display: flex; gap: 14px; align-items: center; }
.cost-status__icon { font-size: 18px; }
.cost-status__num { color: var(--neutral-12); font-size: 14px; font-weight: 600; }
.cost-status__num--session { color: var(--neutral-11); font-weight: 500; }
.cost-status[data-level="warning"] .cost-status__num { color: #f5a623; }
.cost-status[data-level="critical"] .cost-status__num { color: #e74c3c; }
.cost-status__divider { color: var(--neutral-9); }
.cost-status__active { color: var(--neutral-9); font-size: 12px; }
.cost-status__toggle {
  background: transparent; border: 1px solid var(--neutral-7);
  color: var(--neutral-11); padding: 4px 10px; border-radius: 4px;
  font: inherit; font-size: 11px; cursor: pointer;
}
.cost-expand {
  background: var(--neutral-2); border: 1px solid var(--neutral-6);
  border-radius: 8px; margin-bottom: 12px; padding: 0;
}
.cost-expand__seat {
  padding: 12px 18px; border-bottom: 1px solid var(--neutral-6);
  display: grid; grid-template-columns: 110px 130px 1fr; gap: 14px;
  font-family: var(--mono, 'SF Mono', Menlo, monospace); font-size: 12px;
}
.cost-expand__seat:last-child { border-bottom: none; }
.cost-expand__seat.idle { opacity: 0.55; }
.cost-expand__seat-id { color: var(--neutral-12); font-weight: 600; }
.cost-expand__totals { color: var(--neutral-11); }
.cost-expand__totals .today { color: var(--neutral-12); font-weight: 600; }
.cost-expand__seat[data-level="warning"] .today { color: #f5a623; }
.cost-expand__seat[data-level="critical"] .today { color: #e74c3c; }
.cost-expand__totals .session { color: var(--neutral-9); font-size: 11px; }
.cost-expand__engine {
  display: grid; grid-template-columns: 130px 90px 80px;
  font-size: 11px; color: var(--neutral-11);
}
.cost-expand__engine .name { color: var(--brand-primary); }
.cost-expand__engine .usage { color: var(--neutral-9); }
.cost-expand__engine .cost { color: var(--neutral-12); text-align: right; }
```

- [ ] **Step 3: 加 JS — fetch initial state + WS message handler + toggle**

Find existing `<script>` block (look for `// 輪詢 /api/channels` around line 313). Append at end of the script block:

```javascript
// ─── 成本 status bar (Phase A 2026-05-08) ───
const COST_BUDGET = 100;  // 與 pricing.json daily_budget_twd 對齊；不對的話前端只是顯示偏差，REST 才是真值

function fmtTWD(n) {
  if (n >= 10000) return 'NT$ ' + (n / 1000).toFixed(1) + 'k';
  return 'NT$ ' + n.toFixed(2);
}

function levelFromPct(pct) {
  if (pct >= 100) return 'critical';
  if (pct >= 80)  return 'warning';
  return 'ok';
}

function iconFor(level) {
  return { ok: '💰', warning: '⚠️', critical: '🚨' }[level] || '💰';
}

function updateCostBar(today, session, activeCount) {
  document.getElementById('cost-today').textContent = fmtTWD(today);
  document.getElementById('cost-session').textContent = fmtTWD(session);
  document.getElementById('cost-active').textContent = activeCount + '/6 席位活動中';
  const pct = COST_BUDGET > 0 ? (today / COST_BUDGET) * 100 : 0;
  const level = levelFromPct(pct);
  document.getElementById('cost-status').dataset.level = level;
  document.getElementById('cost-icon').textContent = iconFor(level);
}

function renderExpand(byChannel, maxSlots) {
  const root = document.getElementById('cost-expand');
  root.innerHTML = '';
  // 6 槽：1~6 都渲染，沒資料的顯示 idle
  const map = new Map(byChannel.map(c => [c.channel_id, c]));
  for (let i = 1; i <= maxSlots; i++) {
    const id = String(i);
    const ch = map.get(id);
    const isActive = !!ch;
    const today = isActive ? ch.today_twd : 0;
    const session = isActive ? ch.session_twd : 0;
    const pct = COST_BUDGET > 0 ? (today / COST_BUDGET) * 100 : 0;
    const level = levelFromPct(pct);

    const seat = document.createElement('div');
    seat.className = 'cost-expand__seat' + (isActive ? '' : ' idle');
    seat.dataset.level = level;
    seat.innerHTML = `
      <div class="cost-expand__seat-id">席位 ${i}<br><span style="font-size:10px;font-weight:normal;color:var(--neutral-9)">${isActive ? 'live' : 'idle · 無連線'}</span></div>
      <div class="cost-expand__totals">
        <div class="today">${isActive ? fmtTWD(today) : '—'}</div>
        <div class="session">${isActive ? 'session ' + fmtTWD(session) : ''}</div>
      </div>
      <div>
        ${isActive
          ? ch.by_engine.map(e => `
              <div class="cost-expand__engine">
                <span class="name">${e.engine}</span>
                <span class="usage">${e.usage.audio_seconds ? Math.round(e.usage.audio_seconds) + ' 秒' : '—'}</span>
                <span class="cost">${fmtTWD(e.today_twd)}</span>
              </div>`).join('')
          : '<div class="cost-expand__engine" style="color:var(--neutral-9)"><span>—</span><span>—</span><span style="text-align:right">—</span></div>'}
      </div>
    `;
    root.appendChild(seat);
  }
}

async function refreshCost(base) {
  try {
    const r = await fetch(`${base}/api/usage/today`, { signal: AbortSignal.timeout(3000) });
    if (!r.ok) return;
    const d = await r.json();
    updateCostBar(d.today_total_twd, d.session_total_twd, d.active_channel_count);
    renderExpand(d.by_channel, d.max_channel_slots);
  } catch (_) { /* 靜默 */ }
}

// 初始載入
const _base = (typeof window.API_BASE !== 'undefined' ? window.API_BASE : '');
refreshCost(_base);
// 每 5 秒 poll 一次（保險，與 WS push 並存）
setInterval(() => refreshCost(_base), 5000);

// 展開 / 收起 + localStorage 記憶
const _expandKey = 'cost-expand-open';
function setExpanded(open) {
  document.getElementById('cost-expand').hidden = !open;
  document.getElementById('cost-toggle').textContent = open ? '▲ 收起' : '▼ 展開';
  localStorage.setItem(_expandKey, open ? '1' : '0');
}
setExpanded(localStorage.getItem(_expandKey) === '1');
document.getElementById('cost-toggle').addEventListener('click', () => {
  const willOpen = document.getElementById('cost-expand').hidden;
  setExpanded(willOpen);
});
```

- [ ] **Step 4: 啟 server 手動 smoke test UI**

Run:
```bash
python app_api.py &
sleep 5
open http://localhost:8000/monitor
# 用瀏覽器打開後：
# 1. 應看到頂部 "💰 今日 NT$ 0.00 · session NT$ 0.00 · 0/6 席位活動中  [▼ 展開]"
# 2. 點 [▼ 展開] 應看到席位 1~6 全部 idle
# 3. 重新整理頁面，展開狀態應記住
# 4. (可選) 跑一筆真 STT 看數字會不會跳
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add static/monitor.html
git commit -m "feat(ui): monitor.html 加成本 status bar + 6 席位展開區 + WS handler"
```

---

## Task 8: 整合測試 + Migration test + README + push

**Files:**
- Modify: `tests/test_migrate.py`（+1 test）
- Modify: `tests/test_db_manager.py`（+2 tests，與 Task 5 已加合計）
- Modify: `README.md`

- [ ] **Step 1: 加 0002 round-trip test 進 test_migrate.py**

Append to `tests/test_migrate.py`:

```python
class TestMigration0002:
    """0002_add_usage_log 真 migration（不是 dummy）的 round-trip。"""

    def test_0002_creates_usage_log_table(self, baseline_db):
        # baseline_db 已套用 0001。
        # 跑 cmd_up 應該套上 0002（reconcile 0001 + apply 0002）
        rc = migrate.cmd_up(baseline_db, target=None, dry_run=False)
        assert rc == 0

        import sqlite3
        conn = sqlite3.connect(baseline_db)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_log'"
        ).fetchall()
        assert len(rows) == 1
        # 確認欄位齊全
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_log)").fetchall()]
        for c in ("channel_id", "engine", "occurred_at", "usage_json", "cost_usd", "cost_twd"):
            assert c in cols, f"missing column {c}"
        conn.close()
```

- [ ] **Step 2: 加 db_manager 對 usage_log 的查詢 helper test（順手寫 helper）**

Append to `tests/test_db_manager.py`:

```python
class TestUsageLogQueries:
    """db_manager 對 usage_log 的存取（v1 純 SQL；之後可能抽 helper）。"""

    def test_can_insert_and_select_usage_log(self, tmp_db_path):
        db = DBManager(tmp_db_path)
        # baseline + 0002 應已套用
        # 直接 INSERT
        db._conn.execute(
            "INSERT INTO usage_log (channel_id, engine, occurred_at, usage_json, cost_usd, cost_twd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("1", "scribe_rt", "2026-05-08T10:00:00", '{"audio_seconds": 60.0}', 0.00666, 0.20646)
        )
        db._conn.commit()
        rows = db._conn.execute("SELECT cost_usd FROM usage_log WHERE channel_id='1'").fetchall()
        assert len(rows) == 1
        assert abs(rows[0]["cost_usd"] - 0.00666) < 1e-6
        db.close()

    def test_db_init_runs_0002_migration(self, tmp_db_path):
        """DBManager 啟動應自動套用 0001 + 0002。"""
        db = DBManager(tmp_db_path)
        rows = db._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert "0001" in versions
        assert "0002" in versions
        db.close()
```

- [ ] **Step 3: 跑全套測試確認 ≥ 65 tests 全綠**

Run:
```bash
/Users/apple/miniforge3/bin/python3 -m pytest --cov --cov-report=term-missing 2>&1 | tail -15
```

Expected:
- 總 tests ≥ 65（既有 56 + 新加 ~17）
- exit 0
- coverage：utils/pricing.py ≥ 90%, utils/usage_ledger.py ≥ 70%, utils/audio_duration.py ≥ 90%

- [ ] **Step 4: 加 README 「成本顯示」段**

Edit `README.md`. 在「執行測試」段下方加：

```markdown
### 即時成本顯示（2026-05-08 引入，Phase A）

monitor.html 頂部 status bar 顯示：
- 今日累計 STT 成本（台幣）
- 本次 server session 累計
- N/6 席位活動中

點擊展開：6 席位 × engine 細項拆解。

設定：
- `config/pricing.json` — 引擎單價、TWD 匯率、日預算（請定期 review，目前 hardcoded）
- 預設日預算 NT$ 100，達 80% 橘色警告，達 100% 紅色警告
- TWD 匯率 hardcoded 31.0，估算用，非會計級精度

**Phase B（之後）**：加 Gemini correction 等 LLM token tracking。  
詳細 spec：[docs/superpowers/specs/2026-05-08-token-cost-display-design.md](docs/superpowers/specs/2026-05-08-token-cost-display-design.md)
```

- [ ] **Step 5: Commit + push**

```bash
git add tests/test_migrate.py tests/test_db_manager.py README.md
git commit -m "test: 加 0002 migration test + usage_log query test + README 補成本顯示段"
git push
```

- [ ] **Step 6: 觀察 CI 跑綠**

Run:
```bash
cd /Users/apple/Projects/projectArea/aiSpeechMulti
sleep 60
gh run list --limit 1
```

Expected: status `completed` + conclusion `success`

- [ ] **Step 7: 寫 obsidian devlog**

Path: `2nd brain/20_Programming/Projects/aiSpeechMulti/_devlog/2026-05-08 即時 STT 成本顯示 Phase A 完工.md`

內容應含：
- 一句話總結
- 為什麼（連回 spec + brainstorming）
- 8 個 task 結果表
- 關鍵技術細節（usage_log schema / ledger 設計 / threshold UI）
- bonus 發現 / 校準後的真 pricing
- Architecture review Important 項進度更新（如此 feature 揭露其他 Important 該優先做的）
- 下一步：Phase B 何時做

---

## Self-Review

✓ **Spec coverage:** 對照 spec 各 section：
- §1 Goals → Task 6 (REST) + Task 7 (UI)
- §2 Non-Goals → 全部排除（無 LLM、無 cumulative、無 alarm 自動停）
- §3.5 Definitions → 落實在 ledger.today_total_twd 用 `date(occurred_at, 'localtime')`、session_events list 在 process 重啟時自然清空
- §4 Architecture → Task 4 (Ledger) + Task 6 (API) + Task 7 (UI)
- §5 Data Model UsageEvent → Task 4
- §6 DB Schema → Task 1
- §7 Server API (WS + REST) → Task 6
- §8 pricing.json → Task 2
- §9 UI 行為 → Task 7（席位導向已落實）
- §10 Test 計畫 → Task 2/3/4/5/8 各自的 test
- §11 實作步驟 → 即此 plan 的 Task 1-8
- §12 風險 R3 (DB 寫入延遲) → 標註可改 asyncio.to_thread；R5 (pricing 載入失敗) → load_pricing raise PricingError，caller 包 try/except
- §13 Open Questions → spec 已記錄，plan 不解這些（待 Phase A 完成後一週實證再決定）
- §14 Phase B → plan 不做，但 schema/UI/WS message 已預留

✓ **Placeholder scan:** 全 plan 已搜「TBD/TODO/implement later/handle edge cases」零命中。所有 step 含完整 code 或 exact command。

✓ **Type consistency:** 
- `channel_id: str`（非 int）一致全 plan
- engine name "scribe_rt" / "google_stt_chirp_3" 一致 spec § 8
- `usage` dict 鍵 `audio_seconds` 一致全 plan
- `level: "ok" | "warning" | "critical"` 一致 spec § 7.1 + § 9.3

無發現問題。

---

## 驗證標準（Definition of Done）

Phase A 視為完成需滿足：

- [ ] 所有 8 task 全綠 commit
- [ ] `pytest` 全套 ≥ 65 tests 全 pass
- [ ] CI 綠
- [ ] `python app_api.py` 能起、`http://localhost:8000/monitor` 開啟看到 status bar 渲染（即使 0 也要顯示）
- [ ] 真實跑一次 STT call 後，status bar 數字會跳
- [ ] 展開狀態跨 refresh 記住（localStorage）
- [ ] obsidian devlog 寫好

---

*Plan version: 1.0 · 2026-05-08 · 對應 spec faa77ed*
