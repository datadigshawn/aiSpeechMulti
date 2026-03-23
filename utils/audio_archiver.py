#!/usr/bin/env python3
"""
aiSpeech 音檔封存工具
版本: 1.0

功能：
- 將辨識用的原始音檔複製到永久封存目錄
- 計算 SHA-256 雜湊值（確保完整性、避免重複複製）
- 依「年月 / 事件名稱」組織封存目錄結構

封存路徑結構：
    {archive_root}/{YYYYMM}/{event_name}/{original_filename}
    e.g. data/audio_archive/202512/捷運火災/20251222_1922.wav

零外部相依（僅使用 Python 內建 hashlib / shutil / pathlib）。
"""

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

try:
    from .logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)


# 預設封存根目錄
_DEFAULT_ARCHIVE_ROOT = Path(__file__).parent.parent / "data" / "audio_archive"

# 計算 SHA-256 時的讀取區塊大小（8 MB）
_CHUNK_SIZE = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    """計算檔案 SHA-256 雜湊值（hex 字串）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def _safe_dirname(name: str) -> str:
    """
    將事件名稱轉為合法的目錄名稱。
    移除或替換檔案系統不允許的字元（/\\:*?\"<>|）。
    """
    bad_chars = r'/\:*?"<>|'
    for ch in bad_chars:
        name = name.replace(ch, "_")
    name = name.strip(". ")   # 避免開頭或結尾為空白/點
    return name or "unknown_event"


class AudioArchiver:
    """
    音檔封存管理器

    使用方式：
        archiver = AudioArchiver()
        archive_path, sha256, size = archiver.archive_file(
            Path("experiments/temp_upload/source_audio/20251222_1922.wav"),
            event_name="捷運火災"
        )
    """

    def __init__(self, archive_root: Optional[Path] = None):
        """
        初始化封存管理器。

        Args:
            archive_root: 封存根目錄；None 時使用預設路徑
                          (PROJECT_ROOT/data/audio_archive)
        """
        self.archive_root = Path(archive_root) if archive_root else _DEFAULT_ARCHIVE_ROOT
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(self.__class__.__name__)
        self.logger.info(f"音檔封存根目錄：{self.archive_root}")

    def archive_file(
        self,
        src_path: Path,
        event_name: str,
        ref_datetime: Optional[datetime] = None,
    ) -> Tuple[Path, str, int]:
        """
        封存單一音檔。

        目標路徑：{archive_root}/{YYYYMM}/{safe_event_name}/{original_filename}

        若目標已存在且 SHA-256 相同 → 跳過複製（冪等）。
        若 SHA-256 不同（同名不同內容）→ 加上 _1 / _2 ... 後綴後複製。

        Args:
            src_path:     原始音檔路徑（Path）
            event_name:   事件名稱（用於子目錄命名）
            ref_datetime: 用於決定 YYYYMM 目錄的日期；None 時使用當下時間

        Returns:
            Tuple[archive_path, sha256_hex, file_size_bytes]
        """
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(f"原始音檔不存在：{src_path}")

        # 計算來源 hash 與大小
        src_hash = _sha256(src_path)
        src_size = src_path.stat().st_size

        # 決定封存子目錄
        dt = ref_datetime or datetime.now()
        yyyymm = dt.strftime("%Y%m")
        safe_name = _safe_dirname(event_name)
        dest_dir = self.archive_root / yyyymm / safe_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 決定目標檔名（處理同名衝突）
        dest_path = dest_dir / src_path.name
        dest_path = self._resolve_conflict(dest_path, src_hash)

        if dest_path.exists():
            # 同名同 hash → 已封存，直接回傳
            self.logger.info(
                f"跳過封存（已存在，hash 相同）：{dest_path.name}"
            )
        else:
            # 複製並驗證
            shutil.copy2(src_path, dest_path)
            dest_hash = _sha256(dest_path)
            if dest_hash != src_hash:
                dest_path.unlink(missing_ok=True)
                raise IOError(
                    f"封存驗證失敗（hash 不符）：{src_path.name}\n"
                    f"  來源: {src_hash}\n"
                    f"  目標: {dest_hash}"
                )
            self.logger.info(
                f"已封存：{src_path.name} → {dest_path}  "
                f"({src_size:,} bytes)"
            )

        return dest_path, src_hash, src_size

    def archive_files(
        self,
        src_paths: list,
        event_name: str,
        ref_datetime: Optional[datetime] = None,
    ) -> list:
        """
        批次封存多個音檔。

        Args:
            src_paths:    原始音檔路徑列表
            event_name:   事件名稱
            ref_datetime: 參考日期時間

        Returns:
            list of (archive_path, sha256_hex, file_size_bytes)
            失敗的項目以 (None, None, None) 代替並記錄警告。
        """
        results = []
        for src in src_paths:
            try:
                results.append(self.archive_file(src, event_name, ref_datetime))
            except Exception as e:
                self.logger.warning(f"封存失敗 {src}：{e}")
                results.append((None, None, None))
        return results

    # ── 內部工具 ────────────────────────────────────────────────────────────

    def _resolve_conflict(self, dest_path: Path, src_hash: str) -> Path:
        """
        處理同名衝突。

        若目標不存在 → 直接回傳原路徑。
        若目標存在且 hash 相同 → 回傳原路徑（讓呼叫端跳過複製）。
        若目標存在但 hash 不同 → 加後綴 _1, _2, ... 直到找到空位。
        """
        if not dest_path.exists():
            return dest_path

        existing_hash = _sha256(dest_path)
        if existing_hash == src_hash:
            return dest_path   # 已存在且相同，讓呼叫端跳過

        # 同名不同內容 → 加後綴
        stem = dest_path.stem
        suffix = dest_path.suffix
        parent = dest_path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            if _sha256(candidate) == src_hash:
                return candidate   # 已有相同內容的副本
            counter += 1


# ── CLI 測試 ─────────────────────────────────────────────────────────────────

def _cli_test():
    """本地簡易測試（不依賴 Streamlit）。"""
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive_root = tmp / "audio_archive"

        # 建立假音檔
        src = tmp / "20251222_1922.wav"
        src.write_bytes(b"\x00\x01\x02" * 1024)   # 3 KB 假資料

        archiver = AudioArchiver(archive_root)

        # 第一次封存
        dest, h1, sz1 = archiver.archive_file(src, "捷運火災",
                                               ref_datetime=datetime(2025, 12, 22))
        assert dest.exists(), "封存後檔案不存在"
        assert sz1 == src.stat().st_size, "大小不符"
        assert len(h1) == 64, "SHA-256 長度錯誤"

        # 第二次封存（冪等：跳過）
        dest2, h2, sz2 = archiver.archive_file(src, "捷運火災",
                                                ref_datetime=datetime(2025, 12, 22))
        assert dest2 == dest, "冪等路徑不一致"
        assert h2 == h1, "冪等 hash 不一致"

        # 確認目錄結構：audio_archive/202512/捷運火災/20251222_1922.wav
        expected = archive_root / "202512" / "捷運火災" / "20251222_1922.wav"
        assert dest == expected, f"路徑不符: {dest} != {expected}"

        print("✅ AudioArchiver 測試全部通過")
        print(f"   封存路徑：{dest}")
        print(f"   SHA-256：{h1[:16]}…  大小：{sz1:,} bytes")


if __name__ == "__main__":
    _cli_test()
