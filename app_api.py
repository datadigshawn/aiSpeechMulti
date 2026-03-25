#!/usr/bin/env python3
"""
aiSpeechMulti - 五路無線電語音即時辨識 API
版本: 2.0.0 (2026-03-24)

版本歷史:
    v2.0.0 (2026-03-24): 雙引擎串流架構
        - 新增 mode 參數：dual / scribe_rt / google_stream / batch
        - dual 模式：Scribe v2 Realtime（~150ms TTFT）+ Google 批次確認（存 DB）
        - scribe_rt 模式：純 Scribe v2 Realtime 串流
        - google_stream 模式：純 Google streaming_recognize()
        - batch 模式：原有 15 秒批次行為（向下相容）
    v1.2.0 (2026-03-20): 初始版本（單引擎批次）

架構說明（v2.0 dual 模式）:
    瀏覽器 ×5 (Web Audio API → PCM)
        │ WebSocket  /ws/stream/{channel_id}?mode=dual&backend=google
        ▼
    FastAPI — asyncio 管理五路並發
        ├── Scribe v2 Realtime WebSocket ──→ partial/committed → 即時推播前端
        │        wss://api.elevenlabs.io/v1/speech-to-text/realtime
        │        延遲：~150ms TTFT
        │
        └── AudioBuffer（15s 批次）──→ GoogleSTTModel.transcribe_file()
                 ↓ confirmed 結果 → 推播前端 + 存入 SQLite DB
                 ↓
             SQLite (data/aiSpeechMulti.db)
                 ↓
         REST API → Streamlit 儀表板輪詢 (app_dashboard.py)

端點:
    WS   /ws/stream/{channel_id}?mode=dual|scribe_rt|google_stream|batch&backend=google|scribe
    GET  /api/channels    — 管道狀態（含各路引擎與串流模式）
    GET  /api/transcripts — 辨識結果（含 stt_backend 欄位）
    GET  /api/health      — 健康檢查
    GET  /                — 音訊擷取頁面（index.html）
    GET  /monitor         — 五路即時監控頁面（monitor.html）
    GET  /favicon.ico     — 瀏覽器圖示

mode 說明:
    dual         雙引擎並行（推薦）：Scribe RT 即時顯示 + Google 批次確認存庫
    scribe_rt    純 Scribe v2 Realtime 串流（~150ms，不存 DB）
    google_stream 純 Google streaming_recognize()（gRPC 持久連線，自動重連）
    batch        原有 15 秒批次模式（向下相容預設值）
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
from pydantic import BaseModel

# ── 載入 .env ──────────────────────────────────────────────────────────────────
load_dotenv()

# ── 修正 import 路徑（確保 scripts/ utils/ 可被找到）─────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))

from scripts.models.model_google_stt import GoogleSTTModel
from scripts.models.model_scribe import ScribeSTTModel, ScribeRealtimeStream
from utils.logger import get_logger
from utils.vad_filter import has_speech_in_wav_sr
from utils.noise_filter import denoise_wav_file

# ── 簡體→繁體中文轉換（opencc s2twp：台灣繁體用詞）─────────────────────────────
try:
    import opencc as _opencc
    _cc = _opencc.OpenCC("s2twp")   # Simplified → Traditional (Taiwan)

    def _s2t(text: str) -> str:
        """將 Scribe 回傳的簡體中文轉換為繁體中文（台灣用詞）。"""
        if not text:
            return text
        return _cc.convert(text)

except ImportError:
    # opencc 未安裝時降級為原文輸出（不中斷服務）
    def _s2t(text: str) -> str:  # type: ignore[misc]
        return text


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

# ── 串流模式設定 ───────────────────────────────────────────────────────────────
# mode 可為：dual / scribe_rt / google_stream / batch
# dual        = Scribe RT（即時字幕）+ Google 批次（確認存庫） ← 推薦
# scribe_rt   = 純 Scribe v2 Realtime（最低延遲，不存 DB）
# google_stream = 純 Google streaming_recognize()（gRPC，自動重連）
# batch       = 原有 15 秒批次（向下相容）
VALID_MODES         = {"dual", "scribe_rt", "google_stream", "batch"}
DEFAULT_STREAM_MODE = os.getenv("STREAM_MODE", "dual").strip().lower()
if DEFAULT_STREAM_MODE not in VALID_MODES:
    DEFAULT_STREAM_MODE = "dual"

# 預設 STT 引擎：讀自 .env，未設定時回退 google
# 每條 WebSocket 連線可透過 ?backend= 覆蓋此預設值
DEFAULT_STT_BACKEND = os.getenv("STT_BACKEND", "google").strip().lower()
if DEFAULT_STT_BACKEND not in ("google", "scribe"):
    DEFAULT_STT_BACKEND = "google"

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# ── VAD / 降噪開關（執行期可透過 POST /api/settings 動態調整）──────────────
# .env 初始值：USE_VAD / USE_DENOISE / VAD_THRESHOLD
# 無線電建議：USE_VAD=true（過濾靜噪）, USE_DENOISE=false（窄頻音質不適合）
_audio_settings: dict = {
    "use_vad":       os.getenv("USE_VAD",     "false").lower() == "true",
    "use_denoise":   os.getenv("USE_DENOISE", "false").lower() == "true",
    "vad_threshold": float(os.getenv("VAD_THRESHOLD", "0.5")),
}

# 向下相容的模組層級變數（供舊程式碼讀取，實際判斷改用 _audio_settings）
USE_VAD       = _audio_settings["use_vad"]
USE_DENOISE   = _audio_settings["use_denoise"]
VAD_THRESHOLD = _audio_settings["vad_threshold"]

DB_PATH = Path(__file__).parent / "data" / "aiSpeechMulti.db"


# ==============================================================================
# ① 資料結構
# ==============================================================================

@dataclass
class ChannelState:
    """單一管道的執行期狀態"""
    channel_id:       str
    stt_backend:      str      = "google"           # "google" | "scribe"
    stream_mode:      str      = "dual"             # "dual" | "scribe_rt" | "google_stream" | "batch"
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

    def add(self, channel_id: str, stt_backend: str = "google", stream_mode: str = "dual") -> ChannelState:
        state = ChannelState(channel_id=channel_id, stt_backend=stt_backend, stream_mode=stream_mode)
        self.channels[channel_id] = state
        self.logger.info(
            f"✅ 管道 [{channel_id}] 連線　引擎={stt_backend}　模式={stream_mode}　"
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
                    "stream_mode":      c.stream_mode,
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
                    use_vad      INTEGER DEFAULT 0,
                    use_denoise  INTEGER DEFAULT 0,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 相容舊版資料庫：欄位不存在時自動補上
            try:
                conn.execute("ALTER TABLE transcripts ADD COLUMN stt_backend TEXT DEFAULT 'google'")
            except Exception:
                pass
            for col in ("use_vad", "use_denoise"):
                try:
                    conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} INTEGER DEFAULT 0")
                except Exception:
                    pass  # 欄位已存在，忽略
            # 修正既有資料庫中 TEXT 型態的 "0"/"1" → INTEGER
            conn.execute("UPDATE transcripts SET use_vad=0     WHERE use_vad     IS NULL OR use_vad     = ''")
            conn.execute("UPDATE transcripts SET use_denoise=0 WHERE use_denoise IS NULL OR use_denoise = ''")
            conn.execute("UPDATE transcripts SET use_vad=CAST(use_vad AS INTEGER), "
                         "use_denoise=CAST(use_denoise AS INTEGER)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ch ON transcripts(channel_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON transcripts(created_at)")
            conn.commit()

    def save(
        self,
        channel_id:  str,
        transcript:  str,
        confidence:  float = 0.0,
        stt_backend: str   = "google",
        use_vad:     bool  = False,
        use_denoise: bool  = False,
    ):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO transcripts "
                "(channel_id, transcript, confidence, stt_backend, use_vad, use_denoise) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (channel_id, transcript, confidence, stt_backend,
                 int(use_vad), int(use_denoise)),
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
                    "SELECT id, channel_id, transcript, confidence, stt_backend, use_vad, use_denoise, created_at "
                    "FROM transcripts WHERE channel_id = ? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (channel_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, channel_id, transcript, confidence, stt_backend, use_vad, use_denoise, created_at "
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
                "use_vad":     bool(int(r[5] or 0)),
                "use_denoise": bool(int(r[6] or 0)),
                "created_at":  r[7],
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
    logger.info("🚀 aiSpeechMulti API 啟動  v2.0.0")
    logger.info(f"   最大管道數      : {MAX_CHANNELS} 路")
    logger.info(f"   預設串流模式    : {DEFAULT_STREAM_MODE}")
    logger.info(f"   預設 STT 引擎   : {DEFAULT_STT_BACKEND}")
    logger.info(f"   Google STT 模型 : {STT_MODEL} / {STT_LOCATION}")
    logger.info(f"   每段批次長度    : {CHUNK_SECONDS} 秒")
    logger.info(f"   資料庫          : {DB_PATH}")
    logger.info(f"   ElevenLabs Key  : {'已設定 ✅（dual / scribe_rt 可用）' if ELEVENLABS_API_KEY else '未設定 ❌（dual 降級 batch，scribe_rt 不可用）'}")
    logger.info("=" * 60)
    logger.info("串流模式:")
    logger.info("   dual         Scribe RT 即時字幕 + Google 批次確認存庫（推薦）")
    logger.info("   scribe_rt    純 Scribe v2 Realtime（~150ms TTFT）")
    logger.info("   google_stream 純 Google streaming_recognize()（gRPC 自動重連）")
    logger.info("   batch        15 秒批次（向下相容）")
    logger.info("端點列表:")
    logger.info("   WS  ws://0.0.0.0:8000/ws/stream/{channel_id}?mode=dual&backend=google")
    logger.info("   GET http://0.0.0.0:8000/api/channels")
    logger.info("   GET http://0.0.0.0:8000/api/transcripts")
    logger.info("   GET http://0.0.0.0:8000/api/health")
    logger.info("   DOC http://0.0.0.0:8000/docs")
    logger.info("=" * 60)

    yield

    logger.info("🛑 aiSpeechMulti API 關閉  v2.0.0")


app = FastAPI(
    title="aiSpeechMulti API",
    description="五路無線電語音即時辨識系統（dual/scribe_rt/google_stream/batch 四模式）",
    version="2.0.0",
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
# ⑦ 串流模式 Handler（各模式實作）
# ==============================================================================

async def _send_error(ws: WebSocket, channel_id: str, message: str):
    """安全地推送 error 訊息給前端（忽略推送失敗）。"""
    try:
        await ws.send_json({
            "type":       "error",
            "channel_id": channel_id,
            "message":    message,
            "timestamp":  datetime.now().isoformat(),
        })
    except Exception:
        pass


def _preprocess_wav(wav_path: str, channel_id: str = "") -> tuple[str, bool]:
    """
    對 WAV 檔案套用降噪與 VAD 前處理。

    處理流程：
      1. DeepFilterNet 降噪（若 USE_DENOISE=true）
      2. Silero VAD 語音偵測（若 USE_VAD=true）

    Args:
        wav_path:   輸入 WAV 檔案路徑（會原地覆寫）
        channel_id: 用於 log，可空字串

    Returns:
        (wav_path, should_skip)
          should_skip=True → VAD 判定無語音，應跳過 STT
          should_skip=False → 正常送 STT
    """
    tag = f"[{channel_id}]" if channel_id else ""

    # ── Step 1: 降噪 ──────────────────────────────────────────────────────────
    if _audio_settings["use_denoise"]:
        _, ok = denoise_wav_file(wav_path, output_wav=wav_path, sample_rate=SAMPLE_RATE)
        if ok:
            logger.debug(f"{tag}[denoise] 降噪完成")
        else:
            logger.debug(f"{tag}[denoise] 降噪不可用，使用原始音訊")

    # ── Step 2: VAD 篩選 ──────────────────────────────────────────────────────
    if _audio_settings["use_vad"]:
        has_speech = has_speech_in_wav_sr(
            wav_path,
            sample_rate=SAMPLE_RATE,
            threshold=_audio_settings["vad_threshold"],
        )
        if not has_speech:
            logger.debug(f"{tag}[vad] 靜音片段，跳過 STT")
            return wav_path, True   # should_skip = True

    return wav_path, False  # should_skip = False


async def _handle_batch_mode(
    ws: WebSocket, channel_id: str, state: "ChannelState", stt
) -> None:
    """
    原有批次模式（向下相容）：
    PCM 累積 15 秒 → [降噪] → [VAD] → STT → 回傳 transcript + 存庫
    """
    audio_buf = AudioBuffer()

    async for message in ws.iter_bytes():
        audio_buf.append(message)

        if audio_buf.is_ready():
            wav_path = audio_buf.flush_to_wav()
            if not wav_path:
                continue
            try:
                # ── 前處理：降噪 + VAD ─────────────────────────────────────
                _, should_skip = await asyncio.to_thread(
                    _preprocess_wav, wav_path, channel_id
                )
                if should_skip:
                    continue

                result     = await asyncio.to_thread(stt.transcribe_file, wav_path)
                transcript = result.get("transcript", "").strip()
                confidence = result.get("confidence", 0.0)

                if transcript:
                    await ws.send_json({
                        "type":        "transcript",
                        "channel_id":  channel_id,
                        "text":        transcript,
                        "confidence":  round(confidence, 4),
                        "stt_backend": state.stt_backend,
                        "timestamp":   datetime.now().isoformat(),
                    })
                    database.save(channel_id, transcript, confidence, state.stt_backend,
                                  use_vad=_audio_settings["use_vad"],
                                  use_denoise=_audio_settings["use_denoise"])
                    state.transcript_count += 1
                    state.last_text         = transcript
                    logger.debug(f"[{channel_id}][batch] {transcript[:60]}")
                elif result.get("error"):
                    logger.warning(f"[{channel_id}][batch] STT 錯誤：{result['error']}")

            except Exception as exc:
                logger.error(f"[{channel_id}][batch] 辨識例外：{exc}")
                await _send_error(ws, channel_id, str(exc))
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)


async def _handle_scribe_rt_mode(
    ws: WebSocket, channel_id: str, state: "ChannelState"
) -> None:
    """
    純 Scribe v2 Realtime 串流模式：
    PCM → Scribe WebSocket → partial/committed → 推播前端 + 存庫

    修正（v2.0.1）：
        - language_code="" → 讓 Scribe 自動偵測語言（原 "zho" 可能不被支援）
        - ping_interval=None → 避免 ElevenLabs 不回應 ping 導致 ~50s 斷線
        - asyncio.wait(FIRST_COMPLETED) → 任一端斷線立即取消另一任務
    """
    scribe = ScribeRealtimeStream(
        api_key=ELEVENLABS_API_KEY,
        language_code="",       # 空字串 = Scribe 自動偵測（比 "zho" 更穩定）
        sample_rate=SAMPLE_RATE,
        vad_silence_secs=0.6,   # 降低靜音門檻：0.6s 靜音即提交（原 1.5s 太慢）
    )

    try:
        session_id = await scribe.connect()
        logger.info(f"[{channel_id}][scribe_rt] 已連線　session={session_id}")
    except ConnectionError as exc:
        logger.error(f"[{channel_id}][scribe_rt] 連線失敗：{exc}")
        await _send_error(ws, channel_id, f"Scribe RT 連線失敗：{exc}")
        return

    await ws.send_json({
        "type":        "engine_info",
        "channel_id":  channel_id,
        "stt_backend": "scribe_rt",
        "stream_mode": "scribe_rt",
        "session_id":  session_id,
        "timestamp":   datetime.now().isoformat(),
    })

    async def _task_browser_to_scribe():
        """接收瀏覽器 PCM → 轉發給 Scribe。"""
        async for pcm in ws.iter_bytes():
            try:
                await scribe.send_audio(pcm)
            except Exception as exc:
                logger.warning(f"[{channel_id}][scribe_rt] 送音訊失敗：{exc}")
                break

    async def _task_scribe_to_browser():
        """接收 Scribe 結果 → 推播前端 + 存庫。"""
        while scribe.is_connected:
            try:
                msg   = await scribe.receive()
                text  = msg.get("text", "").strip()
                mtype = msg.get("type", "")

                if mtype == "partial" and text:
                    tw = _s2t(text)
                    await ws.send_json({
                        "type":        "partial",
                        "channel_id":  channel_id,
                        "text":        tw,
                        "stt_backend": "scribe_rt",
                        "timestamp":   datetime.now().isoformat(),
                    })

                elif mtype == "committed" and text:
                    tw = _s2t(text)
                    await ws.send_json({
                        "type":        "transcript",
                        "channel_id":  channel_id,
                        "text":        tw,
                        "confidence":  0.0,
                        "stt_backend": "scribe_rt",
                        "timestamp":   datetime.now().isoformat(),
                    })
                    database.save(channel_id, tw, 0.0, "scribe_rt",
                                  use_vad=_audio_settings["use_vad"],
                                  use_denoise=_audio_settings["use_denoise"])
                    state.transcript_count += 1
                    state.last_text         = tw
                    logger.debug(f"[{channel_id}][scribe_rt] committed→DB: {tw[:60]}")

                elif mtype == "session_terminated":
                    logger.info(f"[{channel_id}][scribe_rt] session 結束")
                    break

                elif mtype == "unknown":
                    # 記錄所有未預期訊息（診斷用）
                    raw_type = msg.get("raw", {}).get("message_type", "?")
                    logger.info(f"[{channel_id}][scribe_rt] 收到未知訊息 raw_type={raw_type}　text={text[:40]}")

            except (ConnectionError, RuntimeError) as exc:
                logger.warning(f"[{channel_id}][scribe_rt] 接收中斷：{exc}")
                break

    # ── asyncio.wait(FIRST_COMPLETED)：任一端斷線立即取消另一任務 ────────────
    # 優於 asyncio.gather()：gather 在 Scribe 斷線後仍等待音訊任務，
    # 導致 FastAPI WebSocket 空轉直到 uvicorn keepalive 超時。
    task_b2s = asyncio.create_task(_task_browser_to_scribe(), name=f"b2s_{channel_id}")
    task_s2b = asyncio.create_task(_task_scribe_to_browser(), name=f"s2b_{channel_id}")

    try:
        done, pending = await asyncio.wait(
            [task_b2s, task_s2b],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # 取消尚未完成的任務（例如 Scribe 斷線後取消音訊接收任務）
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        await scribe.close()


async def _handle_google_stream_mode(
    ws: WebSocket, channel_id: str, state: "ChannelState", stt: "GoogleSTTModel"
) -> None:
    """
    純 Google streaming_recognize() 串流模式：
    PCM → gRPC streaming → partial/final → 推播前端 + final 存庫
    自動每 4.5 分鐘重連（Google 限制 5 分鐘）。
    """
    audio_q  = asyncio.Queue(maxsize=100)
    result_q = asyncio.Queue()
    stop_ev  = asyncio.Event()

    await ws.send_json({
        "type":        "engine_info",
        "channel_id":  channel_id,
        "stt_backend": "google_stream",
        "stream_mode": "google_stream",
        "timestamp":   datetime.now().isoformat(),
    })

    async def _task_browser_to_queue():
        """接收瀏覽器 PCM → 放入 audio_q。"""
        async for pcm in ws.iter_bytes():
            try:
                audio_q.put_nowait(pcm)
            except asyncio.QueueFull:
                logger.warning(f"[{channel_id}][google_stream] audio_q 已滿，丟棄 chunk")
        stop_ev.set()   # 瀏覽器斷線時通知串流結束

    async def _task_stream_recognize():
        """驅動 GoogleSTTModel.stream_recognize()。"""
        await stt.stream_recognize(audio_q, result_q, stop_ev)

    async def _task_result_to_browser():
        """從 result_q 取辨識結果 → 推播前端。"""
        while not stop_ev.is_set() or not result_q.empty():
            try:
                result = await asyncio.wait_for(result_q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            text       = result.get("text", "").strip()
            is_final   = result.get("type") == "final"
            confidence = result.get("confidence", 0.0)

            if not text:
                continue

            # 推播前端
            await ws.send_json({
                "type":        "transcript" if is_final else "partial",
                "channel_id":  channel_id,
                "text":        text,
                "confidence":  round(confidence, 4),
                "stt_backend": "google_stream",
                "timestamp":   datetime.now().isoformat(),
            })

            # 僅 final 存庫 + 更新狀態
            if is_final:
                database.save(channel_id, text, confidence, "google_stream",
                              use_vad=_audio_settings["use_vad"],
                              use_denoise=_audio_settings["use_denoise"])
                state.transcript_count += 1
                state.last_text         = text
                logger.debug(f"[{channel_id}][google_stream] final: {text[:60]}")

    await asyncio.gather(
        _task_browser_to_queue(),
        _task_stream_recognize(),
        _task_result_to_browser(),
    )


async def _handle_dual_mode(
    ws: WebSocket, channel_id: str, state: "ChannelState", google_stt: "GoogleSTTModel"
) -> None:
    """
    雙引擎並行模式（推薦）：
        Scribe v2 Realtime  → partial/committed 即時推播前端（~150ms TTFT）
        Google STT 批次      → confirmed 結果存庫 + 推播前端（每 15 秒一次）

    若 Scribe RT 連線失敗，自動回退為純 Google 批次模式。

    前端收到三種訊息類型：
        {"type": "partial",   ...}  — Scribe 中間結果（可能仍會修正）
        {"type": "transcript",...}  — Scribe committed 最終確認
        {"type": "confirmed", ...}  — Google 批次確認（繁體中文，存入 DB）
    """
    scribe    = ScribeRealtimeStream(
        api_key=ELEVENLABS_API_KEY,
        language_code="",       # 空字串 = Scribe 自動偵測（比 "zho" 更穩定）
        sample_rate=SAMPLE_RATE,
        vad_silence_secs=0.6,   # 0.6s 靜音即提交（原 1.5s 太慢）
    )
    audio_buf = AudioBuffer()

    # ── 嘗試連線 Scribe RT ───────────────────────────────────────────────────
    scribe_ok = False
    try:
        session_id = await scribe.connect()
        scribe_ok  = True
        logger.info(f"[{channel_id}][dual] Scribe RT 已連線　session={session_id}")
    except ConnectionError as exc:
        logger.warning(f"[{channel_id}][dual] Scribe RT 連線失敗，回退純批次：{exc}")

    # 告知前端雙引擎狀態
    await ws.send_json({
        "type":         "engine_info",
        "channel_id":   channel_id,
        "stt_backend":  "dual",
        "stream_mode":  "dual",
        "scribe_rt":    scribe_ok,
        "google_batch": True,
        "timestamp":    datetime.now().isoformat(),
    })

    # ── 若 Scribe 不可用，回退批次模式 ───────────────────────────────────────
    if not scribe_ok:
        await _handle_batch_mode(ws, channel_id, state, google_stt)
        return

    # ── Google 批次背景任務 ────────────────────────────────────────────────
    async def _google_batch(wav_path: str):
        """在背景執行降噪 + VAD + Google STT 批次辨識，完成後推播 confirmed + 存庫。"""
        try:
            # ── 前處理：降噪 + VAD ─────────────────────────────────────────
            _, should_skip = await asyncio.to_thread(
                _preprocess_wav, wav_path, channel_id
            )
            if should_skip:
                return

            result     = await asyncio.to_thread(google_stt.transcribe_file, wav_path)
            transcript = result.get("transcript", "").strip()
            confidence = result.get("confidence", 0.0)

            if transcript:
                await ws.send_json({
                    "type":        "confirmed",
                    "channel_id":  channel_id,
                    "text":        transcript,
                    "confidence":  round(confidence, 4),
                    "stt_backend": "google",
                    "timestamp":   datetime.now().isoformat(),
                })
                database.save(channel_id, transcript, confidence, "google",
                              use_vad=_audio_settings["use_vad"],
                              use_denoise=_audio_settings["use_denoise"])
                state.transcript_count += 1
                state.last_text         = transcript
                logger.debug(f"[{channel_id}][dual/google] confirmed: {transcript[:60]}")
            elif result.get("error"):
                logger.warning(f"[{channel_id}][dual/google] STT 錯誤：{result['error']}")

        except Exception as exc:
            logger.error(f"[{channel_id}][dual/google] 批次例外：{exc}")
        finally:
            if os.path.exists(wav_path):
                os.unlink(wav_path)

    # ── Task A：瀏覽器 PCM → Scribe RT + AudioBuffer ─────────────────────
    async def _task_browser_to_both():
        async for pcm in ws.iter_bytes():
            # → Scribe RT（即時）
            if scribe.is_connected:
                try:
                    await scribe.send_audio(pcm)
                except Exception as exc:
                    logger.warning(f"[{channel_id}][dual] Scribe 送音訊失敗：{exc}")

            # → AudioBuffer（Google 批次）
            audio_buf.append(pcm)
            if audio_buf.is_ready():
                wav_path = audio_buf.flush_to_wav()
                if wav_path:
                    asyncio.create_task(_google_batch(wav_path))

    # ── Task B：Scribe RT → 前端 ──────────────────────────────────────────
    async def _task_scribe_to_browser():
        while scribe.is_connected:
            try:
                msg  = await scribe.receive()
                text = msg.get("text", "").strip()
                mtype = msg.get("type", "")

                if mtype == "partial" and text:
                    tw = _s2t(text)
                    await ws.send_json({
                        "type":        "partial",
                        "channel_id":  channel_id,
                        "text":        tw,
                        "stt_backend": "scribe_rt",
                        "timestamp":   datetime.now().isoformat(),
                    })

                elif mtype == "committed" and text:
                    tw = _s2t(text)
                    await ws.send_json({
                        "type":        "transcript",
                        "channel_id":  channel_id,
                        "text":        tw,
                        "confidence":  0.0,
                        "stt_backend": "scribe_rt",
                        "timestamp":   datetime.now().isoformat(),
                    })
                    database.save(channel_id, tw, 0.0, "scribe_rt",
                                  use_vad=_audio_settings["use_vad"],
                                  use_denoise=_audio_settings["use_denoise"])
                    state.transcript_count += 1
                    state.last_text         = tw
                    logger.debug(f"[{channel_id}][dual/scribe] committed→DB: {tw[:60]}")

                elif mtype == "session_terminated":
                    logger.info(f"[{channel_id}][dual/scribe] session 結束")
                    break

                elif mtype == "unknown":
                    raw_type = msg.get("raw", {}).get("message_type", "?")
                    logger.info(f"[{channel_id}][dual/scribe] 未知訊息 raw_type={raw_type}")

            except (ConnectionError, RuntimeError) as exc:
                logger.warning(f"[{channel_id}][dual/scribe] 接收中斷：{exc}")
                break

    # ── 任一端斷線立即取消另一任務（Scribe 斷線後不讓 Google 批次任務孤立） ──
    task_b2b = asyncio.create_task(_task_browser_to_both(), name=f"b2b_{channel_id}")
    task_s2b = asyncio.create_task(_task_scribe_to_browser(), name=f"s2b_{channel_id}")

    try:
        done, pending = await asyncio.wait(
            [task_b2b, task_s2b],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        await scribe.close()
        audio_buf.clear()


# ==============================================================================
# ⑧ WebSocket 端點 — 依 mode 分派至對應 Handler
# ==============================================================================

@app.websocket("/ws/stream/{channel_id}")
async def audio_stream(
    ws:         WebSocket,
    channel_id: str,
    backend: str = Query(default=None,  description="STT 引擎：google | scribe（batch 模式用）"),
    mode:    str = Query(default=None,  description="串流模式：dual | scribe_rt | google_stream | batch"),
):
    """
    五路無線電語音串流端點（v2.0 多模式）。

    query params:
        mode=dual          雙引擎（推薦）：Scribe RT 即時字幕 + Google 批次確認存庫
        mode=scribe_rt     純 Scribe v2 Realtime（最低延遲）
        mode=google_stream 純 Google streaming_recognize()
        mode=batch         原有 15 秒批次（向下相容）
        backend=google     batch 模式用的引擎選擇（google | scribe）

    前端訊息類型：
        engine_info  — 連線成功，說明實際使用的引擎與模式
        partial      — 中間結果（Scribe RT），文字可能仍會修正
        transcript   — Scribe committed 最終確認（低延遲）
        confirmed    — Google 批次確認（繁體中文準確，存入 DB）
        error        — 錯誤訊息
    """
    # ── 參數正規化 ────────────────────────────────────────────────────────────
    mode = (mode or DEFAULT_STREAM_MODE).strip().lower()
    if mode not in VALID_MODES:
        mode = DEFAULT_STREAM_MODE

    backend = (backend or DEFAULT_STT_BACKEND).strip().lower()
    if backend not in ("google", "scribe"):
        backend = "google"

    # ── 容量保護 ──────────────────────────────────────────────────────────────
    if not stream_manager.can_add():
        await ws.close(code=4003, reason=f"管道已滿（上限 {MAX_CHANNELS} 路）")
        return

    # ── ElevenLabs Key 檢查（需要 Scribe 的模式）─────────────────────────────
    needs_scribe = mode in ("dual", "scribe_rt")
    if needs_scribe and not ELEVENLABS_API_KEY:
        if mode == "scribe_rt":
            await ws.close(code=4004, reason="ELEVENLABS_API_KEY 未設定，scribe_rt 不可用")
            return
        else:
            # dual 模式：無 key 時自動降級為 batch
            logger.warning(f"[{channel_id}] ELEVENLABS_API_KEY 未設定，dual 降級為 batch")
            mode = "batch"

    await ws.accept()
    state = stream_manager.add(channel_id, stt_backend=backend, stream_mode=mode)
    logger.info(f"🎙️ [{channel_id}] 連線　mode={mode}　backend={backend}")

    # ── batch / scribe（v1）模式：建立 STT 模型 ───────────────────────────────
    stt = create_stt_model(backend) if mode == "batch" else None

    # dual / google_stream 需要 Google STT 實例
    google_stt = (
        create_stt_model("google")
        if mode in ("dual", "google_stream")
        else None
    )

    # 若 batch 模式，通知前端引擎資訊
    if mode == "batch":
        await ws.send_json({
            "type":        "engine_info",
            "channel_id":  channel_id,
            "stt_backend": backend,
            "stream_mode": "batch",
            "timestamp":   datetime.now().isoformat(),
        })

    try:
        if mode == "dual":
            await _handle_dual_mode(ws, channel_id, state, google_stt)
        elif mode == "scribe_rt":
            await _handle_scribe_rt_mode(ws, channel_id, state)
        elif mode == "google_stream":
            await _handle_google_stream_mode(ws, channel_id, state, google_stt)
        else:
            await _handle_batch_mode(ws, channel_id, state, stt)

    except WebSocketDisconnect:
        logger.info(f"[{channel_id}] 正常斷線")
    except Exception as exc:
        logger.error(f"[{channel_id}] 異常中斷：{exc}")
    finally:
        stream_manager.remove(channel_id)


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


@app.get("/api/test_scribe", summary="Scribe RT 連線診斷（伺服器端直接測試）")
async def test_scribe_rt():
    """
    從伺服器端直接連線 ElevenLabs Scribe v2 Realtime，
    送 2 秒合成音訊 + 1 秒靜音，回傳 Scribe 的原始回應。
    用於診斷 Scribe 連線與 API Key 是否正常。
    """
    import base64, math, struct

    if not ELEVENLABS_API_KEY:
        return {"ok": False, "error": "ELEVENLABS_API_KEY 未設定"}

    def _gen_audio(duration_ms: int, freq: int = 300, srate: int = 16000) -> bytes:
        n = srate * duration_ms // 1000
        return struct.pack("<" + "h" * n,
                           *[int(20000 * math.sin(2 * math.pi * freq * i / srate))
                             for i in range(n)])

    try:
        scribe = ScribeRealtimeStream(
            api_key=ELEVENLABS_API_KEY,
            language_code="",
            sample_rate=16000,
            vad_silence_secs=0.6,
        )
        session_id = await scribe.connect()
    except Exception as exc:
        return {"ok": False, "error": f"Scribe 連線失敗：{exc}"}

    messages = []
    try:
        # 送 2 秒音訊 + 1 秒靜音
        for audio in [_gen_audio(2000), bytes(16000 * 2)]:
            chunk_size = 3200  # 100ms
            for i in range(0, len(audio), chunk_size):
                await scribe.send_audio(audio[i:i + chunk_size])
                await asyncio.sleep(0.02)

        # 收集 4 秒內的回應
        deadline = asyncio.get_event_loop().time() + 4.0
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                msg = await asyncio.wait_for(scribe.receive(), timeout=remaining)
                messages.append(msg)
                if msg["type"] == "session_terminated":
                    break
            except asyncio.TimeoutError:
                break

    except Exception as exc:
        return {"ok": False, "session_id": session_id,
                "error": f"測試過程異常：{exc}", "messages": messages}
    finally:
        await scribe.close()

    return {
        "ok":         True,
        "session_id": session_id,
        "message_count": len(messages),
        "messages":   [{"type": m["type"], "text": m.get("text", ""), "raw_type": m.get("raw", {}).get("message_type", "")} for m in messages],
        "note":       "text 為空=Scribe 運作正常但音訊非語音；有文字=完整正常",
    }


@app.get("/display", include_in_schema=False)
async def display_page():
    """文字投放顯示頁面（適合延伸螢幕全螢幕展示）"""
    return FileResponse("static/display.html")


@app.get("/api/keywords", summary="取得關鍵字清單（供顯示頁關鍵字比對）")
async def get_keywords():
    """
    從 aiSpeechMulti.db 取出所有關鍵字，供 display.html 即時比對。
    回傳格式：[{keyword, hazard_level, source, event_id, event_name}]
    """
    try:
        from utils.db_manager import DBManager as _DBM
        _db = _DBM(DB_PATH)
        rows = _db.get_all_keywords()
        _db.close()
        return {
            "ok": True,
            "keywords": [
                {
                    "keyword":      r[1],
                    "hazard_level": r[2],
                    "source":       r[3],
                    "event_id":     r[4],
                    "event_name":   r[5],
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return {"ok": False, "keywords": [], "error": str(exc)}


@app.get("/api/health", summary="健康檢查")
async def health_check():
    return {
        "status":             "ok",
        "version":            "2.0.0",
        "active_channels":    len(stream_manager.channels),
        "max_channels":       MAX_CHANNELS,
        "default_stream_mode": DEFAULT_STREAM_MODE,
        "default_backend":    DEFAULT_STT_BACKEND,
        "stt_model":          STT_MODEL,
        "stt_language":       STT_LANGUAGE,
        "chunk_seconds":      CHUNK_SECONDS,
        "scribe_available":   bool(ELEVENLABS_API_KEY),
        "modes_available": {
            "dual":          bool(ELEVENLABS_API_KEY),
            "scribe_rt":     bool(ELEVENLABS_API_KEY),
            "google_stream": True,
            "batch":         True,
        },
        "timestamp":          datetime.now().isoformat(),
    }


# ==============================================================================
# ⑨ 音訊前處理設定 API（VAD / 降噪動態開關）
# ==============================================================================

class AudioSettingsBody(BaseModel):
    """PATCH /api/settings 的請求主體（所有欄位可選）"""
    use_vad:       Optional[bool]  = None
    use_denoise:   Optional[bool]  = None
    vad_threshold: Optional[float] = None


@app.get("/api/settings", summary="查詢音訊前處理設定")
async def get_audio_settings():
    """
    回傳目前 VAD 與降噪的開關狀態，以及各模組是否可用。
    前端可用此端點在頁面載入時同步顯示目前設定。
    """
    try:
        from utils.vad_filter    import is_available as vad_available
    except Exception:
        vad_available = lambda: False
    try:
        from utils.noise_filter  import is_available as denoise_available
    except Exception:
        denoise_available = lambda: False

    return {
        "ok": True,
        "settings": dict(_audio_settings),
        "availability": {
            "vad":     vad_available(),
            "denoise": denoise_available(),
        },
    }


@app.post("/api/settings", summary="更新音訊前處理設定")
async def update_audio_settings(body: AudioSettingsBody):
    """
    動態切換 VAD / 降噪開關，無須重啟伺服器。
    僅提供要修改的欄位即可，未提供的欄位保持不變。

    - **use_vad**：Silero VAD 靜音過濾（無線電建議開啟）
    - **use_denoise**：DeepFilterNet 降噪（無線電窄頻建議測試後決定）
    - **vad_threshold**：語音機率門檻 0.0～1.0（預設 0.5，值愈高愈嚴格）
    """
    if body.use_vad is not None:
        _audio_settings["use_vad"] = body.use_vad
    if body.use_denoise is not None:
        _audio_settings["use_denoise"] = body.use_denoise
    if body.vad_threshold is not None:
        _audio_settings["vad_threshold"] = max(0.0, min(1.0, body.vad_threshold))

    logger.info(
        f"[settings] 音訊前處理更新 → "
        f"VAD={'ON' if _audio_settings['use_vad'] else 'OFF'}  "
        f"降噪={'ON' if _audio_settings['use_denoise'] else 'OFF'}  "
        f"VAD門檻={_audio_settings['vad_threshold']}"
    )
    return {"ok": True, "settings": dict(_audio_settings)}


# ==============================================================================
# ⑩ 直接執行入口
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app_api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        # ws_ping_interval / ws_ping_timeout 確保長時間串流連線不被切斷
        ws_ping_interval=20,
        ws_ping_timeout=30,
    )
