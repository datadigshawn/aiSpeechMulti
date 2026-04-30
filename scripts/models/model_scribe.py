#!/usr/bin/env python3
"""
ElevenLabs Scribe 語音辨識模型包裝器
版本: 2.0 (2026-03-24)

變更記錄:
    v2.0 (2026-03-24): 新增 ScribeRealtimeStream（scribe_v2_realtime WebSocket 串流）
    v1.0 (2026-03-20): ScribeSTTModel 批次辨識（scribe_v1）

模組包含：
    ScribeSTTModel       — 批次辨識（HTTP POST，scribe_v1）
    ScribeRealtimeStream — 即時串流（WebSocket，scribe_v2_realtime，~150ms TTFT）

API 文件：
    批次: https://elevenlabs.io/docs/api-reference/speech-to-text
    即時: https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime

使用方式（批次）：
    from scripts.models.model_scribe import ScribeSTTModel
    model = ScribeSTTModel()
    result = model.transcribe_file("audio.wav")
    print(result["transcript"])

使用方式（即時串流，需 asyncio 環境）：
    from scripts.models.model_scribe import ScribeRealtimeStream
    stream = ScribeRealtimeStream(api_key="sk_...")
    await stream.connect()
    await stream.send_audio(pcm_bytes)      # 持續傳送 PCM chunks
    msg = await stream.receive()            # {"type": "partial"|"committed", "text": str}
    await stream.close()

環境變數：
    ELEVENLABS_API_KEY=sk_...   （必填，寫在 .env）
"""

import asyncio
import base64
import json
import logging
import os
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False


class ScribeSTTModel:
    """
    ElevenLabs Scribe v1 語音辨識模型包裝器。

    與 GoogleSTTModel 相同介面，可直接替換使用：
        result = model.transcribe_file(wav_path)
        transcript = result["transcript"]
        confidence = result["confidence"]

    Scribe 支援格式：WAV / MP3 / M4A / FLAC / OGG / WEBM
    Scribe 語言：自動偵測，或指定 language_code 提示（如 "zh"）
    """

    API_URL  = "https://api.elevenlabs.io/v1/speech-to-text"
    MODEL_ID = "scribe_v1"

    def __init__(
        self,
        language_code: str  = "zh",    # "zh" 提示偏中文；留空("")讓 Scribe 全自動偵測
        diarize:       bool = False,    # True = 啟用講者辨識（結果含 speaker_id）
        timeout:       float = 60.0,   # HTTP 請求逾時秒數
    ):
        self.api_key      = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.language_code = language_code
        self.diarize      = diarize
        self.timeout      = timeout

        if not self.api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY 未設定，請在 .env 加入：\n"
                "ELEVENLABS_API_KEY=sk_..."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 主要介面
    # ─────────────────────────────────────────────────────────────────────────

    def transcribe_file(self, audio_file, with_word_confidence: bool = True) -> dict:
        """
        辨識音檔，回傳格式與 GoogleSTTModel 完全相容。

        Args:
            audio_file: 音檔路徑（str 或 Path），建議使用 16kHz mono WAV
            with_word_confidence: True 時取 word-level timestamps + logprob
                                  並回傳 'words' 欄位（#5 逐字 confidence 標記用）

        Returns:
            成功：{
                "transcript": str,
                "confidence": float,
                "words": list[{text, start, end, confidence}]  # 若 with_word_confidence=True
            }
            失敗：{"transcript": "", "confidence": 0.0, "error": str}
        """
        audio_path = Path(audio_file)

        try:
            audio_bytes = audio_path.read_bytes()

            # ── multipart/form-data 請求欄位 ──────────────────────────────────
            form_data: dict = {
                "model_id":               self.MODEL_ID,
                "diarize":                "true" if self.diarize else "false",
                # word-level：取得逐字時間戳 + logprob（用於 confidence 標記）
                "timestamps_granularity": "word" if with_word_confidence else "none",
            }
            if self.language_code:
                form_data["language_code"] = self.language_code

            # ── 送出 HTTP POST ────────────────────────────────────────────────
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.API_URL,
                    headers={"xi-api-key": self.api_key},
                    data=form_data,
                    files={"file": (audio_path.name, audio_bytes, "audio/wav")},
                )

            # ── 解析回應 ─────────────────────────────────────────────────────
            if resp.status_code != 200:
                return {
                    "transcript": "",
                    "confidence": 0.0,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }

            data = resp.json()
            result = {
                "transcript": (data.get("text") or "").strip(),
                # language_confidence：Scribe 對語言偵測的信心值（0.0–1.0）
                # 注意：與 Google chirp_3 的 word confidence 定義不同，僅供參考
                "confidence": float(data.get("language_confidence") or 0.0),
            }

            # word-level confidence（若有要求）
            if with_word_confidence:
                words = data.get("words") or []
                # 每個 word 物件含 text/type/start/end/logprob/speaker_id
                # confidence ≈ exp(logprob)（logprob 通常為負，越接近 0 越高信心）
                import math
                normalized_words = []
                for w in words:
                    if w.get("type") not in ("word", None):
                        continue  # 跳過 spacing / audio_event
                    logprob = w.get("logprob")
                    if logprob is None:
                        conf = 1.0  # 無資訊預設高信心，避免誤標
                    else:
                        try:
                            conf = float(math.exp(float(logprob)))
                        except Exception:
                            conf = 1.0
                    normalized_words.append({
                        "text":       w.get("text", ""),
                        "start":      w.get("start"),
                        "end":        w.get("end"),
                        "confidence": round(conf, 4),
                    })
                result["words"] = normalized_words

            return result

        except httpx.TimeoutException:
            return {
                "transcript": "",
                "confidence": 0.0,
                "error": f"Scribe API 請求逾時（>{self.timeout}s）",
            }
        except Exception as exc:
            return {
                "transcript": "",
                "confidence": 0.0,
                "error": str(exc),
            }


# ==============================================================================
# ScribeRealtimeStream — ElevenLabs Scribe v2 Realtime WebSocket 串流器
# ==============================================================================

class ScribeRealtimeStream:
    """
    ElevenLabs Scribe v2 Realtime WebSocket 即時串流辨識器。

    特性：
        - 首字延遲（TTFT）~150ms，最佳條件下 30–80ms
        - 伺服器端 VAD 自動切分語句（commit_strategy="vad"）
        - 支援 partial_transcript（邊說邊顯示）+ committed_transcript（最終確認）
        - 音訊格式：PCM 16-bit signed little-endian，16kHz mono

    使用方式（asyncio 環境）：
        stream = ScribeRealtimeStream(api_key="sk_...")
        await stream.connect()
        try:
            await stream.send_audio(pcm_bytes)   # 可多次呼叫
            msg = await stream.receive()
            # msg["type"] = "partial" | "committed" | "session_terminated"
            # msg["text"] = 辨識文字
        finally:
            await stream.close()

    WebSocket 端點（ElevenLabs 2026-01-06 發布）：
        wss://api.elevenlabs.io/v1/speech-to-text/realtime
        模型：scribe_v2_realtime

    ⚠️  注意事項：
        - 繁體中文（zh-TW）輸出未有官方明確確認，實測可能輸出簡體
        - 詞彙表 keyterm 功能僅 batch 版支援，realtime 版不支援
        - 需要 websockets 套件：pip install websockets
    """

    WS_URL   = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
    MODEL_ID = "scribe_v2_realtime"

    def __init__(
        self,
        api_key:         str,
        language_code:   str   = "zho",   # "zho"=普通話；""=Scribe 自動偵測
        sample_rate:     int   = 16000,   # 支援: 8000/16000/22050/24000/44100/48000
        commit_strategy: str   = "vad",   # "vad"=自動；"manual"=手動呼叫 commit
        vad_threshold:   float = 0.4,     # VAD 靈敏度（0–1，越高越嚴格）
        vad_silence_secs: float = 1.5,   # 靜音多久後提交（秒）
    ):
        if not _HAS_WEBSOCKETS:
            raise ImportError(
                "ScribeRealtimeStream 需要 websockets 套件：pip install websockets"
            )
        if not api_key:
            raise ValueError("api_key 不可為空（請設定 ELEVENLABS_API_KEY）")

        self.api_key          = api_key
        self.language_code    = language_code
        self.sample_rate      = sample_rate
        self.commit_strategy  = commit_strategy
        self.vad_threshold    = vad_threshold
        self.vad_silence_secs = vad_silence_secs

        self._ws:         object | None = None   # websockets.WebSocketClientProtocol
        self._session_id: str | None    = None

    # ── 屬性 ─────────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """
        回傳 WebSocket 連線是否有效。

        相容性說明：
            websockets < 10   → 連線物件有 .closed (bool)
            websockets 10–13  → WebSocketClientProtocol，.closed 仍是 bool
            websockets 14+    → ClientConnection，改用 .state (OPEN=1, CLOSED=3)
                                不再有 .closed 屬性
        """
        if self._ws is None:
            return False
        # websockets 14+ (ClientConnection): 用 state 判斷
        if hasattr(self._ws, "state"):
            try:
                return int(self._ws.state) == 1   # OPEN = 1
            except Exception:
                return False
        # websockets < 14 (WebSocketClientProtocol): 用 closed 判斷
        return not getattr(self._ws, "closed", True)

    @property
    def session_id(self) -> str | None:
        """ElevenLabs 分配的工作階段 ID（連線後有效）。"""
        return self._session_id

    # ── 連線管理 ──────────────────────────────────────────────────────────────

    def _build_url(self) -> str:
        """組合 WebSocket 連線 URL（含 query params）。"""
        parts = [
            self.WS_URL,
            f"?model_id={self.MODEL_ID}",
            f"&audio_format=pcm_{self.sample_rate}",
            f"&commit_strategy={self.commit_strategy}",
        ]
        if self.language_code:
            parts.append(f"&language_code={self.language_code}")
        if self.commit_strategy == "vad":
            parts.append(f"&vad_threshold={self.vad_threshold}")
            parts.append(f"&vad_silence_threshold_secs={self.vad_silence_secs}")
        return "".join(parts)

    async def connect(self) -> str:
        """
        建立 WebSocket 連線並等待 session_started 確認。

        Returns:
            session_id（ElevenLabs 分配的工作階段 ID）

        Raises:
            ConnectionError: 連線失敗、逾時或收到非預期的初始訊息
        """
        url     = self._build_url()
        headers = {"xi-api-key": self.api_key}

        try:
            # ⚠️ ping_interval=None：ElevenLabs Scribe RT 不回應 WebSocket ping frames，
            #    若啟用 ping（預設 20s），websockets 會在 ping_interval+ping_timeout≈50s
            #    後自動斷線（close reason: "keepalive ping timeout"）。
            #    ElevenLabs 使用自己的應用層心跳，不需要 WebSocket 層 ping。
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=None,   # 停用 WebSocket ping，避免 ~50s 超時斷線
                close_timeout=10,
            )

            # 等待 session_started（最多 10 秒）
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            msg = json.loads(raw)

            if msg.get("message_type") != "session_started":
                raise ConnectionError(
                    f"預期 session_started，實際收到：{msg.get('message_type')} "
                    f"/ 原始訊息：{raw[:300]}"
                )

            self._session_id = msg.get("session_id", "")
            return self._session_id

        except asyncio.TimeoutError as exc:
            self._ws = None
            raise ConnectionError("Scribe RT 連線逾時（10s 內未收到 session_started）") from exc
        except Exception as exc:
            self._ws = None
            raise ConnectionError(f"Scribe RT 連線失敗：{exc}") from exc

    async def close(self) -> None:
        """安全關閉 WebSocket 連線。"""
        if self._ws and self.is_connected:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws         = None
        self._session_id = None

    # ── 音訊傳送 ──────────────────────────────────────────────────────────────

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """
        傳送一個 PCM 音訊 chunk 給 Scribe。

        音訊規格：
            - 格式：PCM 16-bit signed little-endian
            - 取樣率：與初始化時 sample_rate 相同（預設 16000）
            - 聲道：mono（單聲道）

        Args:
            pcm_chunk: 原始 PCM bytes，長度不限（建議 100–500ms）

        Raises:
            RuntimeError: 尚未連線（未呼叫 connect() 或已斷線）
        """
        if not self.is_connected:
            raise RuntimeError("尚未連線，請先呼叫 connect()")

        payload = json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm_chunk).decode(),
            "commit":        False,
            "sample_rate":   self.sample_rate,
        })
        await self._ws.send(payload)

    async def commit(self) -> None:
        """
        手動提交當前語段（僅 commit_strategy="manual" 時使用）。
        VAD 模式下 Scribe 會自動偵測靜音提交，無需呼叫此方法。
        """
        if not self.is_connected:
            raise RuntimeError("尚未連線")
        payload = json.dumps({"message_type": "input_audio_chunk", "commit": True,
                               "audio_base_64": "", "sample_rate": self.sample_rate})
        await self._ws.send(payload)

    # ── 結果接收 ──────────────────────────────────────────────────────────────

    async def receive(self) -> dict:
        """
        阻塞等待並接收一則辨識訊息（unified 格式）。

        Returns:
            統一格式 dict：
            {
                "type":       "partial" | "committed" | "session_terminated" | "unknown",
                "text":       str,        # 辨識文字（partial / committed 有此欄位）
                "raw":        dict,       # ElevenLabs 原始訊息
            }

            type 說明：
                "partial"    — 即時中間結果，文字可能仍會修正，適合即時字幕顯示
                "committed"  — 最終確認結果，可存入資料庫
                "session_terminated" — 工作階段結束

        Raises:
            RuntimeError: 尚未連線
            ConnectionError: WebSocket 已斷線
        """
        if not self.is_connected:
            raise RuntimeError("尚未連線")

        try:
            raw_str = await self._ws.recv()
            raw     = json.loads(raw_str)
        except Exception as exc:
            raise ConnectionError(f"Scribe RT 接收失敗：{exc}") from exc

        mtype = raw.get("message_type", "")
        text  = (raw.get("text") or "").strip()

        if mtype == "partial_transcript":
            return {"type": "partial",   "text": text, "raw": raw}
        elif mtype == "committed_transcript":
            return {"type": "committed", "text": text, "raw": raw}
        elif mtype == "session_terminated":
            return {"type": "session_terminated", "text": "", "raw": raw}
        else:
            # 記錄所有未預期的訊息類型（幫助診斷 Scribe RT API 問題）
            _log.debug("Scribe RT 未知訊息類型：%s　原始：%s", mtype, str(raw)[:200])
            return {"type": "unknown", "text": text, "raw": raw}

    async def receive_loop(self, on_partial=None, on_committed=None) -> None:
        """
        持續接收辨識結果直到連線中斷，呼叫對應的 callback。

        Args:
            on_partial:   async def on_partial(text: str) — 收到 partial 時呼叫
            on_committed: async def on_committed(text: str) — 收到 committed 時呼叫

        適用情境：搭配 asyncio.create_task() 在背景持續接收結果。
        """
        while self.is_connected:
            try:
                msg = await self.receive()
            except (ConnectionError, RuntimeError):
                break

            if msg["type"] == "partial" and on_partial and msg["text"]:
                await on_partial(msg["text"])
            elif msg["type"] == "committed" and on_committed and msg["text"]:
                await on_committed(msg["text"])
            elif msg["type"] == "session_terminated":
                break
