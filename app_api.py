#!/usr/bin/env python3
"""
aiSpeechMulti - 五路無線電語音即時辨識 API
版本: 1.2.0 (2026-03-20)

架構說明:
    瀏覽器 ×5 (Web Audio API → PCM)
        │ WebSocket  /ws/stream/{channel_id}?backend=google|scribe
        ▼
    FastAPI (本檔案) — asyncio 管理五路並發
        │ asyncio.to_thread() — Thread 包裝同步 STT
        ▼
    GoogleSTTModel (chirp_3)  ─── 或 ───  ScribeSTTModel (scribe_v1)
        │                                        │
        └──────────────┬─────────────────────────┘
                       ▼
              SQLite (data/aiSpeechMulti.db)
                  transcripts 表（含 stt_backend 欄位）
                       │
          REST API → Streamlit 儀表板輪詢 (app_dashboard.py)

端點:
    WS   /ws/stream/{channel_id}?backend=google|scribe  — 音訊串流
    GET  /api/channels    — 管道狀態（含各路引擎）
    GET  /api/transcripts — 辨識結果（含 stt_backend 欄位）
    GET  /api/health      — 健康檢查
    GET  /                — 音訊擷取頁面（index.html）
    GET  /monitor         — 五路即時監控頁面（monitor.html）
    GET  /favicon.ico     — 瀏覽器圖示

引擎切換:
    每條 WebSocket 連線可獨立指定引擎：
        ws://localhost:8000/ws/stream/ch1?backend=google
        ws://localhost:8000/ws/stream/ch2?backend=scribe
    預設值由 .env 的 STT_BACKEND 決定（未指定 query param 時）。
"""

import asyncio
import os
import sqlite3
import tempfile
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── 載入 .env ──────────────────────────────────────────────────────────────────
load_dotenv()

# ── 修正 import 路徑（確保 scripts/ utils/ 可被找到）─────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))

from scripts.models.model_google_stt import GoogleSTTModel
from scripts.models.model_scribe import ScribeSTTModel
from utils.logger import get_logger


# ==============================================================================
# 全域設定
# ==============================================================================

MAX_CHANNELS      = 5
PROJECT_ID        = os.getenv("GOOGLE_CLOUD_PROJECT", "dazzling-seat-315406")
STT_MODEL         = "chirp_3"
STT_LANGUAGE      = "cmn-Hant-TW"
STT_LOCATION      = "asia-northeast1"
SAMPLE_RATE       = 16000
CHUNK_SECONDS     = 15
BYTES_PER_SAMPLE  = 2
TARGET_BYTES      = SAMPLE_RATE * CHUNK_SECONDS * BYTES_PER_SAMPLE  # 480,000 bytes

# 預設 STT 引擎：讀自 .env，未設定時回退 google
# 每條 WebSocket 連線可透過 ?backend= 覆蓋此預設值
DEFAULT_STT_BACKEND = os.getenv("STT_BACKEND", "google").strip().lower()
if DEFAULT_STT_BACKEND not in ("google", "scribe"):
    DEFAULT_STT_BACKEND = "google"

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

DB_PATH = Path(__file__).parent / "data" / "aiSpeechMulti.db"


# ==============================================================================
# ① 資料結構
# ==============================================================================

@dataclass
class ChannelState:
    """單一管道的執行期狀態"""
    channel_id:       str
    stt_backend:      str      = "google"           # "google" | "scribe"
    connected_at:     datetime = field(default_factory=datetime.now)
    transcript_count: int      = 0
    last_text:        str      = ""
    is_active:        bool     = True


# ==============================================================================
# ② StreamManager — 五路管道生命週期管理
# ==============================================================================

class StreamManager:
    """管理最多 MAX_CHANNELS 路音訊管道。"""

    def __init__(self):
        self.channels: Dict[str, ChannelState] = {}
        self.logger = get_logger("StreamManager")

    def can_add(self) -> bool:
        active = sum(1 for c in self.channels.values() if c.is_active)
        return active < MAX_CHANNELS

    def add(self, channel_id: str, stt_backend: str = "google") -> ChannelState:
        state = ChannelState(channel_id=channel_id, stt_backend=stt_backend)
        self.channels[channel_id] = state
        self.logger.info(
            f"✅ 管道 [{channel_id}] 連線　引擎={stt_backend}　"
            f"（目前 {len(self.channels)}/{MAX_CHANNELS} 路）"
        )
        return state

    def remove(self, channel_id: str):
        if channel_id in self.channels:
            del self.channels[channel_id]
            self.logger.info(
                f"🔌 管道 [{channel_id}] 斷線　"
                f"（剩餘 {len(self.channels)}/{MAX_CHANNELS} 路）"
            )

    def snapshot(self) -> dict:
        return {
            "max_channels":      MAX_CHANNELS,
            "active_channels":   len(self.channels),
            "default_backend":   DEFAULT_STT_BACKEND,
            "channels": [
                {
                    "id":               c.channel_id,
                    "stt_backend":      c.stt_backend,
                    "connected_at":     c.connected_at.isoformat(),
                    "transcript_count": c.transcript_count,
                    "last_text":        (c.last_text[:60] + "…")
                                        if len(c.last_text) > 60
                                        else c.last_text,
                }
                for c in self.channels.values()
            ],
        }


# ==============================================================================
# ③ AudioBuffer — PCM 緩衝區
# ==============================================================================

class AudioBuffer:
    def __init__(self):
        self._buf = bytearray()

    def append(self, data: bytes):
        self._buf.extend(data)

    def is_ready(self) -> bool:
        return len(self._buf) >= TARGET_BYTES

    def flush_to_wav(self) -> Optional[str]:
        if not self._buf:
            return None
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        try:
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(BYTES_PER_SAMPLE)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(bytes(self._buf))
            os.close(fd)
            self._buf = bytearray()
            return tmp_path
        except Exception:
            os.close(fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return None

    def clear(self):
        self._buf = bytearray()


# ==============================================================================
# ④ Database — SQLite 輕量持久化
# ==============================================================================

class Database:
    """
    SQLite 資料庫，儲存辨識結果。
    transcripts 表含 stt_backend 欄位，記錄每筆辨識使用的引擎。
    相容舊版資料庫：ALTER TABLE 自動補欄位。
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id   TEXT    NOT NULL,
                    transcript   TEXT    NOT NULL,
                    confidence   REAL    DEFAULT 0.0,
                    stt_backend  TEXT    DEFAULT 'google',
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 相容舊版資料庫：若 stt_backend 欄位不存在則自動新增
            try:
                conn.execute("ALTER TABLE transcripts ADD COLUMN stt_backend TEXT DEFAULT 'google'")
            except Exception:
                pass  # 欄位已存在，忽略
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ch ON transcripts(channel_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON transcripts(created_at)")
            conn.commit()

    def save(
        self,
        channel_id:  str,
        transcript:  str,
        confidence:  float = 0.0,
        stt_backend: str   = "google",
    ):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO transcripts (channel_id, transcript, confidence, stt_backend) "
                "VALUES (?, ?, ?, ?)",
                (channel_id, transcript, confidence, stt_backend),
            )
            conn.commit()

    def query(
        self,
        limit:      int           = 50,
        channel_id: Optional[str] = None,
        offset:     int           = 0,
    ) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            if channel_id:
                rows = conn.execute(
                    "SELECT id, channel_id, transcript, confidence, stt_backend, created_at "
                    "FROM transcripts WHERE channel_id = ? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (channel_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, channel_id, transcript, confidence, stt_backend, created_at "
                    "FROM transcripts "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()

        return [
            {
                "id":          r[0],
                "channel_id":  r[1],
                "transcript":  r[2],
                "confidence":  r[3],
                "stt_backend": r[4] or "google",
                "created_at":  r[5],
            }
            for r in rows
        ]


# ==============================================================================
# ⑤ STT 工廠函式
# ==============================================================================

def create_stt_model(backend: str = "google"):
    """
    依 backend 參數建立對應的 STT 模型實例。

    Args:
        backend: "google" → GoogleSTTModel (chirp_3)
                 "scribe" → ScribeSTTModel (ElevenLabs scribe_v1)

    每條 WebSocket 連線各自持有一個實例，避免跨管道共用狀態。
    """
    if backend == "scribe":
        return ScribeSTTModel(
            language_code="zh",   # 提示偏中文，可留空讓 Scribe 自動偵測
            diarize=False,
        )
    else:
        return GoogleSTTModel(
            project_id=PROJECT_ID,
            location=STT_LOCATION,
            model=STT_MODEL,
            language_code=STT_LANGUAGE,
            auto_convert_audio=True,
            use_config_manager=True,
        )


# ==============================================================================
# ⑥ FastAPI App 與全域物件
# ==============================================================================

stream_manager = StreamManager()
database       = Database(DB_PATH)
logger         = get_logger("app_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("🚀 aiSpeechMulti API 啟動  v1.2.0")
    logger.info(f"   最大管道數     : {MAX_CHANNELS} 路")
    logger.info(f"   預設 STT 引擎  : {DEFAULT_STT_BACKEND}")
    logger.info(f"   Google STT 模型: {STT_MODEL} / {STT_LOCATION}")
    logger.info(f"   每段辨識長度   : {CHUNK_SECONDS} 秒")
    logger.info(f"   資料庫         : {DB_PATH}")
    logger.info(f"   ElevenLabs Key : {'已設定' if ELEVENLABS_API_KEY else '未設定（Scribe 不可用）'}")
    logger.info("=" * 60)
    logger.info("端點列表:")
    logger.info("   WS  ws://0.0.0.0:8000/ws/stream/{channel_id}?backend=google|scribe")
    logger.info("   GET http://0.0.0.0:8000/api/channels")
    logger.info("   GET http://0.0.0.0:8000/api/transcripts")
    logger.info("   GET http://0.0.0.0:8000/api/health")
    logger.info("   DOC http://0.0.0.0:8000/docs")
    logger.info("=" * 60)

    yield

    logger.info("🛑 aiSpeechMulti API 關閉")


app = FastAPI(
    title="aiSpeechMulti API",
    description="五路無線電語音即時辨識系統（支援 Google STT / ElevenLabs Scribe）",
    version="1.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


_NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html", headers=_NO_CACHE)


@app.get("/monitor", include_in_schema=False)
async def monitor():
    return FileResponse("static/monitor.html", headers=_NO_CACHE)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


# ==============================================================================
# ⑦ WebSocket 端點 — 核心串流邏輯
# ==============================================================================

@app.websocket("/ws/stream/{channel_id}")
async def audio_stream(
    ws:         WebSocket,
    channel_id: str,
    backend:    str = Query(default=None, description="STT 引擎：google 或 scribe"),
):
    """
    接收瀏覽器 PCM 音訊 → 累積 15 秒 → 送 STT → 回傳辨識文字。

    query param:
        backend=google   使用 Google chirp_3（預設）
        backend=scribe   使用 ElevenLabs Scribe v1

    若未指定 backend，使用 .env 的 STT_BACKEND 設定值。
    五路管道可各自指定不同引擎，互不影響。
    """
    # 未指定時用環境變數預設值
    if backend is None:
        backend = DEFAULT_STT_BACKEND
    backend = backend.strip().lower()
    if backend not in ("google", "scribe"):
        backend = "google"

    # ── 容量保護 ──────────────────────────────────────────────────────────────
    if not stream_manager.can_add():
        await ws.close(code=4003, reason=f"管道已滿（上限 {MAX_CHANNELS} 路）")
        return

    # ── Scribe 可用性檢查 ─────────────────────────────────────────────────────
    if backend == "scribe" and not ELEVENLABS_API_KEY:
        await ws.close(code=4004, reason="ELEVENLABS_API_KEY 未設定，Scribe 不可用")
        return

    await ws.accept()
    state     = stream_manager.add(channel_id, stt_backend=backend)
    audio_buf = AudioBuffer()
    stt       = create_stt_model(backend)

    logger.info(f"🎙️ 管道 [{channel_id}] 開始接收音訊　引擎={backend}")

    # 告知前端實際使用的引擎
    await ws.send_json({
        "type":        "engine_info",
        "channel_id":  channel_id,
        "stt_backend": backend,
        "timestamp":   datetime.now().isoformat(),
    })

    try:
        async for message in ws.iter_bytes():

            # ① 累積 PCM
            audio_buf.append(message)

            # ② 達到 15 秒 → 送辨識
            if audio_buf.is_ready():
                wav_path = audio_buf.flush_to_wav()
                if not wav_path:
                    continue

                try:
                    # ③ Thread 包裝：同步 STT → 非阻塞
                    result = await asyncio.to_thread(
                        stt.transcribe_file, wav_path
                    )

                    transcript = result.get("transcript", "").strip()
                    confidence = result.get("confidence", 0.0)

                    if transcript:
                        # ④ 回傳前端
                        await ws.send_json({
                            "type":        "transcript",
                            "channel_id":  channel_id,
                            "text":        transcript,
                            "confidence":  round(confidence, 4),
                            "stt_backend": backend,
                            "timestamp":   datetime.now().isoformat(),
                        })

                        # ⑤ 存庫（含引擎資訊）
                        database.save(channel_id, transcript, confidence, backend)

                        # ⑥ 更新管道狀態
                        state.transcript_count += 1
                        state.last_text         = transcript

                        logger.debug(
                            f"管道 [{channel_id}][{backend}] 辨識完成：{transcript[:60]}"
                        )

                    elif result.get("error"):
                        logger.warning(
                            f"管道 [{channel_id}][{backend}] STT 錯誤：{result['error']}"
                        )

                except Exception as exc:
                    logger.error(f"管道 [{channel_id}] 辨識例外：{exc}")
                    try:
                        await ws.send_json({
                            "type":       "error",
                            "channel_id": channel_id,
                            "message":    str(exc),
                            "timestamp":  datetime.now().isoformat(),
                        })
                    except Exception:
                        pass

                finally:
                    if os.path.exists(wav_path):
                        os.unlink(wav_path)

    except WebSocketDisconnect:
        logger.info(f"管道 [{channel_id}] 正常斷線")

    except Exception as exc:
        logger.error(f"管道 [{channel_id}] 異常中斷：{exc}")

    finally:
        stream_manager.remove(channel_id)
        audio_buf.clear()


# ==============================================================================
# ⑧ REST API 端點
# ==============================================================================

@app.get("/api/channels", summary="查詢五路管道即時狀態")
async def get_channels():
    """
    回傳各管道連線時間、辨識筆數、最新文字、使用引擎。
    stt_backend 欄位為各路實際使用的引擎（google / scribe）。
    """
    return stream_manager.snapshot()


@app.get("/api/transcripts", summary="查詢辨識結果")
async def get_transcripts(
    limit:      int           = Query(50,   ge=1, le=500),
    offset:     int           = Query(0,    ge=0),
    channel_id: Optional[str] = Query(None),
):
    """查詢歷史辨識結果，含 stt_backend 欄位。"""
    results = database.query(limit=limit, channel_id=channel_id, offset=offset)
    return {
        "transcripts": results,
        "count":       len(results),
        "limit":       limit,
        "offset":      offset,
        "channel_id":  channel_id,
    }


@app.get("/api/health", summary="健康檢查")
async def health_check():
    return {
        "status":           "ok",
        "active_channels":  len(stream_manager.channels),
        "max_channels":     MAX_CHANNELS,
        "default_backend":  DEFAULT_STT_BACKEND,
        "stt_model":        STT_MODEL,
        "stt_language":     STT_LANGUAGE,
        "chunk_seconds":    CHUNK_SECONDS,
        "scribe_available": bool(ELEVENLABS_API_KEY),
        "timestamp":        datetime.now().isoformat(),
    }


# ==============================================================================
# ⑨ 直接執行入口
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app_api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
