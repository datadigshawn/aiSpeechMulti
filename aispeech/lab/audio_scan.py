"""伺服器音檔掃描純邏輯（自 app_lab.py 抽出並參數化，2026-06-16 P3 第一波）。

原 app_lab.scan_server_audio_files() 依賴模組全域 EXPERIMENTS_DIR /
SUPPORTED_EXTENSIONS；抽出時改為顯式參數，去除隱性耦合、便於測試。
"""

from __future__ import annotations

from pathlib import Path


def scan_server_audio_files(
    experiments_dir: Path,
    extensions: list[str],
) -> dict:
    """掃描 experiments_dir 下各 test case 的 source_audio/ 音檔。

    Args:
        experiments_dir: experiments/ 根目錄。
        extensions: 支援副檔名清單（如 ['.wav', '.mp3']）。

    Returns:
        {test_case_name: [sorted Path, ...]}；temp_upload 與無 source_audio 者略過。
    """
    result: dict = {}
    if not experiments_dir.exists():
        return result
    for test_case_dir in sorted(experiments_dir.iterdir()):
        if not test_case_dir.is_dir() or test_case_dir.name == "temp_upload":
            continue
        audio_dir = test_case_dir / "source_audio"
        if not audio_dir.exists():
            continue
        files = []
        for ext in extensions:
            files.extend(audio_dir.glob(f"*{ext}"))
            files.extend(audio_dir.glob(f"*{ext.upper()}"))
        if files:
            result[test_case_dir.name] = sorted(set(files))
    return result
