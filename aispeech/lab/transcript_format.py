"""逐字稿格式化純邏輯（自 app_lab.py 原封抽出，2026-06-16 P3 第一波）。"""

from __future__ import annotations

from datetime import datetime, timedelta as _td


def format_with_per_sentence_timestamps(
    transcript: str,
    segments: list[dict] | None,
    start_dt: datetime | None,
    audio_duration_sec: float | None = None,
) -> str:
    """把整段逐字稿轉成「[HH:MM:SS] sentence。」逐句多行格式。

    時間戳優先序：
    1. segments 內有「真實時間區間」(seg_end > seg_start) → 用 segment 區間 + 字數比例
    2. 否則用 audio_duration_sec → 整段視為 [0, audio_duration_sec]，按字數比例分散
    3. 否則第一句用 start_dt、其餘留空白對齊
    4. start_dt 為 None → 只切句不加時間
    """
    if not transcript or not transcript.strip():
        return transcript

    def _split_sentences(text: str) -> list[str]:
        parts = [p.strip() for p in text.split("。")]
        out = []
        for i, p in enumerate(parts):
            if not p:
                continue
            if i < len(parts) - 1:
                out.append(p + "。")
            else:
                out.append(p)
        return out

    lines: list[str] = []

    if start_dt is None:
        return "\n".join(_split_sentences(transcript))

    # ── 1. segments 有真實時間區間 ────────────────────────────────────
    has_real_timing = bool(segments) and any(
        (float(s.get("end", 0)) - float(s.get("start", 0))) > 0
        for s in segments
    )
    if has_real_timing:
        for seg in segments:
            seg_text = (seg.get("text") or "").strip()
            if not seg_text:
                continue
            sents = _split_sentences(seg_text)
            if not sents:
                continue
            seg_start = float(seg.get("start", 0.0))
            seg_end = float(seg.get("end", seg_start))
            seg_dur = max(0.0, seg_end - seg_start)
            total_chars = sum(len(s) for s in sents)
            cum_chars = 0
            for sent in sents:
                offset = seg_dur * (cum_chars / total_chars) if (total_chars and seg_dur) else 0.0
                sent_dt = start_dt + _td(seconds=seg_start + offset)
                lines.append(f"[{sent_dt.strftime('%H:%M:%S')}] {sent}")
                cum_chars += len(sent)
        return "\n".join(lines)

    # ── 2. 無有效 segment 時間，但有音檔長度 → 整段按字數比例分散 ──────
    if audio_duration_sec and audio_duration_sec > 0:
        sents = _split_sentences(transcript)
        total_chars = sum(len(s) for s in sents)
        cum_chars = 0
        for sent in sents:
            offset = audio_duration_sec * (cum_chars / total_chars) if total_chars else 0.0
            sent_dt = start_dt + _td(seconds=offset)
            lines.append(f"[{sent_dt.strftime('%H:%M:%S')}] {sent}")
            cum_chars += len(sent)
        return "\n".join(lines)

    # ── 3. 兩者都沒有 → 第一句用 start_dt，其餘留空白對齊 ──────────────
    blank_ts = " " * 10
    sents = _split_sentences(transcript)
    for i, sent in enumerate(sents):
        if i == 0:
            lines.append(f"[{start_dt.strftime('%H:%M:%S')}] {sent}")
        else:
            lines.append(f"{blank_ts} {sent}")
    return "\n".join(lines)
