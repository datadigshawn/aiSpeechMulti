"""Tests for aispeech.lab 純函式（自 app_lab.py 抽出，2026-06-16 P3 第一波）。

重點覆蓋 format_with_per_sentence_timestamps 的 4 條時間戳分支 —— 這段 80 行
邏輯原本卡在 app_lab God file、完全無測試。
"""

from __future__ import annotations

from datetime import datetime

from aispeech.lab.transcript_format import format_with_per_sentence_timestamps
from aispeech.lab.audio_scan import scan_server_audio_files


START = datetime(2026, 6, 16, 9, 0, 0)


class TestFormatPerSentenceTimestamps:
    def test_empty_returns_as_is(self):
        assert format_with_per_sentence_timestamps("", None, START) == ""
        assert format_with_per_sentence_timestamps("   ", None, START) == "   "

    def test_no_start_dt_just_splits(self):
        """分支 4：start_dt 為 None → 只切句不加時間。"""
        out = format_with_per_sentence_timestamps("第一句。第二句。", None, None)
        assert out == "第一句。\n第二句。"
        assert "[" not in out

    def test_segments_real_timing(self):
        """分支 1：segment 有真實時間區間 → 用 segment 起點對齊。"""
        segs = [{"start": 0.0, "end": 10.0, "text": "第一句。第二句。"}]
        out = format_with_per_sentence_timestamps("忽略整段", segs, START)
        lines = out.split("\n")
        assert len(lines) == 2
        # 第一句落在 segment 起點 09:00:00
        assert lines[0].startswith("[09:00:00] 第一句。")
        # 第二句 offset 在 0~10s 內，仍是 09:00:0x
        assert lines[1].startswith("[09:00:0")
        assert "第二句。" in lines[1]

    def test_audio_duration_proportional(self):
        """分支 2：無 segment 時間但有 audio_duration_sec → 按字數比例分散。"""
        # 兩句等長，第二句 offset ≈ 一半時長
        out = format_with_per_sentence_timestamps(
            "甲甲甲甲。乙乙乙乙。", None, START, audio_duration_sec=100.0)
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("[09:00:00]")
        # 第二句約在 50s（"甲甲甲甲。"=5字 / 10字 → 50s）→ 09:00:50
        assert lines[1].startswith("[09:00:50]")

    def test_first_sentence_only_then_blank_align(self):
        """分支 3：無 segment 也無 duration → 首句加時間、其餘空白對齊。"""
        out = format_with_per_sentence_timestamps("第一句。第二句。", None, START)
        lines = out.split("\n")
        assert lines[0].startswith("[09:00:00] 第一句。")
        assert lines[1].startswith(" " * 10)
        assert "第二句。" in lines[1]


class TestScanServerAudioFiles:
    def test_missing_dir_returns_empty(self, tmp_path):
        assert scan_server_audio_files(tmp_path / "nope", [".wav"]) == {}

    def test_scans_source_audio_skips_temp_upload(self, tmp_path):
        # case1/source_audio/a.wav, b.MP3（大小寫都吃）
        (tmp_path / "case1" / "source_audio").mkdir(parents=True)
        (tmp_path / "case1" / "source_audio" / "a.wav").write_bytes(b"x")
        (tmp_path / "case1" / "source_audio" / "b.MP3").write_bytes(b"x")
        # temp_upload 應略過
        (tmp_path / "temp_upload" / "source_audio").mkdir(parents=True)
        (tmp_path / "temp_upload" / "source_audio" / "c.wav").write_bytes(b"x")
        # 無 source_audio 的 case 應略過
        (tmp_path / "case2").mkdir()

        out = scan_server_audio_files(tmp_path, [".wav", ".mp3"])
        assert set(out.keys()) == {"case1"}
        names = sorted(p.name for p in out["case1"])
        assert names == ["a.wav", "b.MP3"]
