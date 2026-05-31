"""
YouTube 影片音軌擷取工具

以 yt-dlp（系統 binary）下載 YouTube 影片並抽取為 16kHz mono WAV，
供後續 STT 管線使用。檔名帶入影片標題以便回溯來源。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# 預設儲存位置（相對 vault 根目錄）
DEFAULT_OUT_DIR = Path("experiments/temp_youtube")

# 用 `python -m yt_dlp` 而不是直接呼叫 `yt-dlp` binary，避免 PATH 解析到舊版的
# brew/系統版本（兩個 yt-dlp 共存時 PATH 順序不可靠）
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]

# 檔案系統不允許的字元 / 易出問題的標點
_UNSAFE_FS_CHARS = re.compile(r'[\\/:*?"<>|\n\r\t]')


def sanitize_title(title: str, max_len: int = 80) -> str:
    """把影片標題清成檔案系統安全的字串。

    - 移除 \\ / : * ? " < > | 與換行/tab
    - 多重空白縮成單一底線
    - 截斷至 max_len 字元（避免超過 ext4/HFS+ 檔名限制）
    """
    if not title:
        return "untitled"
    cleaned = _UNSAFE_FS_CHARS.sub("", title)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")
    return cleaned or "untitled"


def probe(url: str, timeout: int = 30) -> dict:
    """讀取 YouTube 影片 metadata（不下載）。

    回傳 dict: {id, title, duration_s, uploader, webpage_url}
    失敗時 raise RuntimeError，訊息含 yt-dlp stderr 摘要。
    """
    try:
        proc = subprocess.run(
            YTDLP_CMD + ["-j", "--skip-download", "--no-warnings", url],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("yt_dlp 未安裝於目前 Python 環境（pip install -U yt-dlp）")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp probe 逾時（{timeout}s）— 網路或影片過大")

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError("yt-dlp probe 失敗: " + " / ".join(stderr_tail) or "未知錯誤")

    try:
        info = json.loads(proc.stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise RuntimeError(f"無法解析 yt-dlp 輸出: {e}")

    return {
        "id":          info.get("id", ""),
        "title":       info.get("title", "untitled"),
        "duration_s":  int(info.get("duration") or 0),
        "uploader":    info.get("uploader", "") or info.get("channel", ""),
        "webpage_url": info.get("webpage_url", url),
    }


def download_audio(
    url: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    timeout: int = 600,
) -> Path:
    """下載音軌為 16kHz mono WAV，回傳檔案路徑。

    檔名格式：`<sanitized_title>__<video_id>.wav`
    若同 video_id 的檔案已存在，**直接回傳既有路徑**（不重抓）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 先 probe 拿 title + id 來決定檔名
    info = probe(url)
    safe_title = sanitize_title(info["title"])
    video_id = info["id"] or "unknown"
    target = out_dir / f"{safe_title}__{video_id}.wav"

    if target.exists() and target.stat().st_size > 0:
        return target

    # 用 yt-dlp 抽音檔；-f bestaudio/best 讓 fallback 也能用「video 含 audio」格式
    # （加 -x 後 ffmpeg 會從 video 抽音軌出來）
    base_cmd = YTDLP_CMD + [
        "-f", "bestaudio/best",
        "-x", "--audio-format", "wav",
        "--postprocessor-args", "-ar 16000 -ac 1",
        "--no-warnings",
        "-o", str(out_dir / f"{safe_title}__{video_id}.%(ext)s"),
    ]

    # YouTube 對不同 player client 給不同保護等級；fallback 順序：
    #   1. default — 通常有最完整 audio-only 格式（DASH 49k/129k）
    #   2. android — 通常剩 format 18（360p mp4 含音軌），無 PO Token 需求
    #   3. ios     — 多數情境需 GVS PO Token，最後嘗試
    attempts = [
        ("default", base_cmd + [url]),
        ("android", base_cmd + ["--extractor-args", "youtube:player_client=android", url]),
        ("ios",     base_cmd + ["--extractor-args", "youtube:player_client=ios", url]),
    ]
    errors_by_label: list[str] = []
    for label, cmd in attempts:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0 and target.exists():
            return target
        stderr = (proc.stderr or "").strip()
        tail = " ".join(stderr.splitlines()[-2:]) if stderr else "(no stderr)"
        errors_by_label.append(f"[{label}] {tail}")
        # 只在 403 / format unavailable / SABR 時繼續 fallback；其他錯（無效 URL 等）直接停
        if not any(k in stderr for k in (
            "403", "Forbidden", "Requested format is not available",
            "SABR", "unable to download",
        )):
            break

    raise RuntimeError("yt-dlp 下載失敗（已試 default/android/ios client）:\n  " + "\n  ".join(errors_by_label))


def estimate_cost_twd(
    duration_s: int,
    engine: str = "google_stt_chirp_3",
    pricing_path: Optional[Path] = None,
) -> dict:
    """依 config/pricing.json 估算 STT 成本。

    回傳 dict: {usd, twd, usd_per_unit, usd_to_twd, duration_min}
    若引擎不存在於 pricing.json 則 raise KeyError。
    """
    if pricing_path is None:
        pricing_path = Path(__file__).parent.parent / "config" / "pricing.json"
    pricing = json.loads(Path(pricing_path).read_text(encoding="utf-8"))

    if engine not in pricing.get("engines", {}):
        raise KeyError(f"pricing.json 沒有引擎 '{engine}'")

    cfg = pricing["engines"][engine]
    usd = duration_s * cfg["usd_per_unit"]
    rate = pricing.get("usd_to_twd", 31.0)
    return {
        "usd":           round(usd, 4),
        "twd":           round(usd * rate, 2),
        "usd_per_unit":  cfg["usd_per_unit"],
        "usd_to_twd":    rate,
        "duration_min":  round(duration_s / 60, 1),
        "engine":        engine,
    }
