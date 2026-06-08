"""句級時間定位：把 SenseVoice 的 segments（或純文字）轉成「每句 + 絕對時間」。

主力辨識仍是 SenseVoice；本模組只負責把它已回傳的 segment 時間（VAD 句界）
換算成牆鐘絕對時間，不需 Paraformer。

絕對時間 = session 起始時間（檔名解析 / 串流連線時間）+ 句在音檔內的 offset。

結構化輸出（非顯示字串）：
    [{"text", "start_ms", "end_ms", "abs_time"(ISO|None)}, ...]
顯示用格式（[HH:MM:SS] 句）見 app_lab.format_with_per_sentence_timestamps。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 檔名任意位置的 YYYYMMDD_HHMMSS（容忍 - 或 _ 分隔）
# 同時支援 radio_20251201_140000 與 001_daily_UltraLog060_20260321_154438
_DT_RE = re.compile(r"(\d{8})[_\-](\d{6})")
# 句子切分：中文句號為主，容忍 ！？及換行
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?])")


def session_start_from_filename(path) -> Optional[datetime]:
    """從檔名抓 session 起始時間（找 YYYYMMDD_HHMMSS）；找不到回 None。"""
    m = _DT_RE.search(Path(path).stem)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    try:
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]),
                        int(t[:2]), int(t[2:4]), int(t[4:6]))
    except ValueError:
        return None


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text or "")]
    return [p for p in parts if p]


def _abs_iso(session_start: Optional[datetime], offset_sec: float) -> Optional[str]:
    if session_start is None:
        return None
    return (session_start + timedelta(seconds=offset_sec)).isoformat()


def localize_sentences(
    segments: Optional[list[dict]] = None,
    session_start: Optional[datetime] = None,
    base_offset_sec: float = 0.0,
    transcript: Optional[str] = None,
    audio_duration_sec: Optional[float] = None,
) -> list[dict]:
    """回傳每句 {text, start_ms, end_ms, abs_time}。

    Args:
        segments: SenseVoice transcribe_file 的 segments（[{start,end,text}], 秒）。
        session_start: session 起始 datetime（檔名解析或串流連線時間）；None → abs_time=None。
        base_offset_sec: 整段在 session 內的偏移（即時串流時=該 chunk 的起始秒）。
        transcript: 無 segments 時的 fallback 全文（按 。 切 + audio_duration 比例分時）。
        audio_duration_sec: fallback 用的音檔總長。

    每個 VAD segment 內再按 。 切句，段內時間以字數比例分配（與 app_lab 顯示邏輯一致）。
    """
    out: list[dict] = []

    if segments:
        for seg in segments:
            s0 = float(seg.get("start", 0.0)) + base_offset_sec
            s1 = float(seg.get("end", s0)) + base_offset_sec
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            sents = _split_sentences(text)
            if len(sents) <= 1:
                out.append({
                    "text": text,
                    "start_ms": int(s0 * 1000),
                    "end_ms": int(s1 * 1000),
                    "abs_time": _abs_iso(session_start, s0),
                })
                continue
            # 段內按字數比例分時
            total_chars = sum(len(x) for x in sents) or 1
            span = max(s1 - s0, 0.0)
            cursor = s0
            for x in sents:
                frac = len(x) / total_chars
                e = cursor + span * frac
                out.append({
                    "text": x,
                    "start_ms": int(cursor * 1000),
                    "end_ms": int(e * 1000),
                    "abs_time": _abs_iso(session_start, cursor),
                })
                cursor = e
        return out

    # fallback：無 segment 時間 → 全文按 。 切，用 audio_duration 比例分配
    sents = _split_sentences(transcript or "")
    if not sents:
        return out
    dur = float(audio_duration_sec or 0.0)
    total_chars = sum(len(x) for x in sents) or 1
    cursor = base_offset_sec
    for x in sents:
        frac = len(x) / total_chars
        e = cursor + dur * frac
        out.append({
            "text": x,
            "start_ms": int(cursor * 1000),
            "end_ms": int(e * 1000) if dur else None,
            "abs_time": _abs_iso(session_start, cursor),
        })
        cursor = e
    return out
