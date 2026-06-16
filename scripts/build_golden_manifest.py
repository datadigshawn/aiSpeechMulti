#!/usr/bin/env python3
"""
黃金語料集 Manifest 自動產生腳本
================================

掃描 experiments/golden_dataset/ 內的 audio/ 與 ground_truth/，
自動配對並產出 manifest.csv 索引清單。

配對規則：
    audio/001_daily_xxx.wav  ↔  ground_truth/001_daily_xxx.txt
    （檔名相同，副檔名不同）

輸出 manifest.csv 欄位：
    id              - 順序編號（從檔名解析，例如 "001"）
    event_type      - 主類事件（單值；sidecar event_types.csv 優先，否則檔名解析/fallback）
    tags            - 多標籤事件（pipe 分隔，如 emergency|control；僅供 CER 診斷加總）
    audio_file      - 音檔相對路徑
    gt_file         - GT 文字檔相對路徑
    duration_sec    - 音檔時長（秒）
    gt_char_count   - GT 字數（不含標點與空白）
    gt_speaker_lines - GT 講者行數
    audio_size_kb   - 音檔大小（KB）
    audio_format    - 音檔格式（wav/mp3/m4a...）
    has_gt          - 是否已有對應的 GT（True/False）
    notes           - 備註欄位（手動編輯用，腳本會保留既有值）

用法：
    # 基本使用
    python3 scripts/build_golden_manifest.py

    # 指定不同的目錄
    python3 scripts/build_golden_manifest.py \\
        --audio-dir experiments/golden_dataset/audio \\
        --gt-dir experiments/golden_dataset/ground_truth \\
        --output experiments/golden_dataset/manifest.csv

    # 只列出未配對的音檔（找出還沒寫 GT 的）
    python3 scripts/build_golden_manifest.py --list-missing
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional

# Windows cp950 OEMCP 不能 encode emoji，強制 stdout/stderr 用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = PROJECT_ROOT / "experiments" / "golden_dataset"

# ── 支援的音檔格式 ─────────────────────────────────────────────────
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

# ── 檔名解析正則 ───────────────────────────────────────────────────
# 範例:
#   001_daily_UltraLog063_20260321_154513.wav     ← 原始批次（3 位數字）
#   G0001_emergency_席位1_2025122_192236.wav      ← 後續批次（字母前綴 + 4 位數字）
# 接受兩種：純數字 ≥3 位，或字母前綴後接 ≥3 位數字
FILENAME_PATTERN = re.compile(r"^([A-Z]?\d{3,4})_(\w+?)_(.+)$")

# 已知事件類型（用於驗證）；incident = 檔名解析不出屬性的事故批次 fallback
KNOWN_EVENT_TYPES = {"daily", "door", "track", "emergency", "control", "incident"}

# 事故批次檔名關鍵詞（如 260603_北屯機廠號誌故障_…）→ event_type=incident
INCIDENT_KEYWORDS = ("故障", "異常", "事故", "停電", "跳電", "搶修")

# 主類優先級：多情境段落取唯一主類（高風險優先），驅動分層切分與 history
EVENT_PRECEDENCE = ("emergency", "control", "door", "track", "daily")

# event_type 真相來源 sidecar（檔名不再標事件類；id → event_type/tags）
DEFAULT_EVENT_TYPES_CSV = DEFAULT_DATASET_DIR / "event_types.csv"


def derive_primary(tags: list[str]) -> str:
    """從多標籤依優先級取唯一主類；無命中則取第一個 tag。"""
    for et in EVENT_PRECEDENCE:
        if et in tags:
            return et
    return tags[0] if tags else ""


def infer_event_type(stem: str) -> str:
    """檔名解析不出 event_type token 時，依關鍵詞歸類。"""
    for kw in INCIDENT_KEYWORDS:
        if kw in stem:
            return "incident"
    return "unknown"


def parse_filename(filename: str) -> dict:
    """解析檔名取得 id 與 event_type。

    正則匹配成功 → 取既有 (id, event_type, rest)。
    匹配失敗（如事故批次 `260603_北屯機廠號誌故障_…`：6 位日期開頭、
    中文事件名）→ **不再回 None 丟棄**，改用 stem 當 id、依關鍵詞推斷
    event_type（故障/異常→incident，否則 unknown），確保資料不被靜默
    排除在 manifest（進而訓練集）之外。屬性落在 event_type 欄位、不靠
    檔名 token，往後純時間命名的檔也能被收錄並自動歸類。
    """
    stem = Path(filename).stem
    match = FILENAME_PATTERN.match(stem)
    if match:
        return {
            "id": match.group(1),
            "event_type": match.group(2),
            "rest": match.group(3),
            "stem": stem,
        }
    return {
        "id": stem,
        "event_type": infer_event_type(stem),
        "rest": "",
        "stem": stem,
    }


def soundfile_available() -> bool:
    """偵測 soundfile(libsndfile) 是否可用。

    時長讀取以 soundfile 為主、wave 為退路；但這批 wav 多非標準 PCM、
    且 mp3 wave 根本讀不了 → 缺 soundfile 時時長會大量留空，連帶
    finetune jsonl 的 source_len 歸零。故開跑前先測，提早警告。
    """
    try:
        import soundfile  # noqa: F401
        return True
    except Exception:
        return False


def get_audio_duration(audio_path: Path) -> Optional[float]:
    """嘗試取得音檔時長（用 soundfile 或 wave）"""
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        return round(info.duration, 2)
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(audio_path), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate(), 2)
    except Exception:
        return None


def count_gt_chars(gt_path: Path) -> tuple[int, int]:
    """計算 GT 字數（去除標點/空白/講者標記）與講者行數"""
    if not gt_path.exists():
        return 0, 0
    text = gt_path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    speaker_lines = sum(1 for ln in lines if re.match(r"^[A-Z?]:\s*", ln))

    # 去除講者標記
    clean = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    # 去除標點與空白
    clean = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\u201c\u201d\[\]【】]+", "", clean)
    return len(clean), speaker_lines


def load_existing_notes(manifest_path: Path) -> dict[str, str]:
    """從現有 manifest.csv 載入 notes 欄位（保留人工編輯內容）"""
    notes = {}
    if not manifest_path.exists():
        return notes
    try:
        with open(manifest_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fid = row.get("id", "")
                note = row.get("notes", "")
                if fid and note:
                    notes[fid] = note
    except Exception:
        pass
    return notes


def load_event_types(path: Path) -> dict[str, dict]:
    """讀 sidecar event_types.csv（id → {event_type, tags}）。

    sidecar 是 event_type 的真相來源（檔名不再標事件類）。每列：
        id, event_type, tags
    - tags：多標籤，pipe 分隔（如 emergency|control），僅供 CER 診斷加總。
    - event_type（主類，單值）：留空時依 EVENT_PRECEDENCE 從 tags 自動取
      最高風險者，確保多情境段落歸唯一一格（分層切分要求）。
    - id 以 `#` 開頭的列視為註解，略過。
    回傳 {id: {"event_type": str, "tags": [str, ...]}}。
    """
    overrides: dict[str, dict] = {}
    if not path.exists():
        return overrides
    try:
        with open(path, encoding="utf-8-sig") as f:
            # 先濾掉 `#` 註解列，否則開頭註解會被 DictReader 誤當表頭
            data_lines = [ln for ln in f if not ln.lstrip().startswith("#")]
        for row in csv.DictReader(data_lines):
            fid = (row.get("id") or "").strip()
            if not fid or fid.startswith("#"):
                continue
            tags = [t.strip() for t in (row.get("tags") or "").split("|") if t.strip()]
            et = (row.get("event_type") or "").strip()
            if not et:
                et = derive_primary(tags)
            if et and et not in tags:
                tags = [et] + tags   # 確保主類也在 tags（診斷會計入主類）
            overrides[fid] = {"event_type": et or "unknown", "tags": tags}
    except Exception as e:
        print(f"⚠️  讀取 event_types sidecar 失敗（忽略，沿用檔名解析）: {e}")
    return overrides


def scan_dataset(audio_dir: Path, gt_dir: Path, existing_notes: dict[str, str],
                 event_types: dict[str, dict]) -> list[dict]:
    """掃描音檔與 GT，產出記錄清單"""
    if not audio_dir.exists():
        print(f"❌ audio 目錄不存在: {audio_dir}")
        return []

    rows = []
    audio_files = sorted(
        [f for f in audio_dir.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]
    )

    for audio_path in audio_files:
        # parse_filename 一律回 dict（解析失敗用 stem 當 id + 關鍵詞推斷
        # event_type），不再丟棄任何音檔
        parsed = parse_filename(audio_path.name)

        # 對應的 GT 檔
        gt_path = gt_dir / f"{parsed['stem']}.txt"

        duration = get_audio_duration(audio_path)
        gt_chars, speaker_lines = count_gt_chars(gt_path)
        # has_gt 需「存在且內容非空」——空白 placeholder 不算已標註（否則空檔會被當成已 GT）
        has_gt = gt_path.exists() and gt_chars > 0

        # event_type / tags：sidecar 優先（真相來源），無則沿用檔名解析/fallback
        override = event_types.get(parsed["id"])
        if override:
            event_type = override["event_type"]
            tags = override["tags"]
        else:
            event_type = parsed["event_type"]
            tags = [event_type] if event_type != "unknown" else []

        row = {
            "id": parsed["id"],
            "event_type": event_type,
            "tags": "|".join(tags),
            "audio_file": str(audio_path.relative_to(PROJECT_ROOT)),
            "gt_file": str(gt_path.relative_to(PROJECT_ROOT)),
            "duration_sec": duration if duration else "",
            "gt_char_count": gt_chars,
            "gt_speaker_lines": speaker_lines,
            "audio_size_kb": round(audio_path.stat().st_size / 1024, 1),
            "audio_format": audio_path.suffix.lstrip("."),
            "has_gt": "Y" if has_gt else "N",
            "notes": existing_notes.get(parsed["id"], ""),
        }

        # 驗證事件類型：fallback 自動猜的（incident/unknown）且未經 sidecar 確認 → 提醒補 sidecar
        if not override and event_type in ("incident", "unknown"):
            row["notes"] = (row["notes"] + " [⚠️ event_type 待 sidecar 確認]").strip()
        elif event_type not in KNOWN_EVENT_TYPES:
            row["notes"] = (row["notes"] + " [⚠️ unknown event_type]").strip()

        rows.append(row)

    return rows


def write_manifest(rows: list[dict], output_path: Path) -> None:
    """寫出 manifest CSV"""
    if not rows:
        print("⚠️  沒有資料可寫入")
        return

    fieldnames = [
        "id", "event_type", "tags", "audio_file", "gt_file",
        "duration_sec", "gt_char_count", "gt_speaker_lines",
        "audio_size_kb", "audio_format", "has_gt", "notes",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def print_stats(rows: list[dict]) -> None:
    """列印統計摘要"""
    if not rows:
        return
    total = len(rows)
    with_gt = sum(1 for r in rows if r["has_gt"] == "Y")
    by_type: dict[str, int] = {}
    by_type_with_gt: dict[str, int] = {}
    total_duration = 0.0
    total_gt_chars = 0

    for r in rows:
        et = r["event_type"]
        by_type[et] = by_type.get(et, 0) + 1
        if r["has_gt"] == "Y":
            by_type_with_gt[et] = by_type_with_gt.get(et, 0) + 1
        if isinstance(r["duration_sec"], (int, float)):
            total_duration += r["duration_sec"]
        total_gt_chars += r["gt_char_count"]

    print()
    print("═" * 60)
    print("📊 黃金語料集統計")
    print("═" * 60)
    print(f"   總段數:         {total}")
    print(f"   已有 GT:        {with_gt} / {total} ({with_gt*100//max(total,1)}%)")
    print(f"   總時長:         {total_duration:.1f}s ({total_duration/60:.1f} 分鐘)")
    print(f"   GT 總字數:      {total_gt_chars}")
    print()
    print("   ── 依事件主類分佈（單值，總和 = 段數）──")
    for et in sorted(by_type.keys()):
        with_gt_count = by_type_with_gt.get(et, 0)
        print(f"   {et:12} {by_type[et]:3} 段  (已標 {with_gt_count:3})")

    # tags 分佈（多標籤，一段可計入多類，總和 > 段數）
    tag_cnt: dict[str, int] = {}
    for r in rows:
        for t in (r.get("tags") or "").split("|"):
            if t:
                tag_cnt[t] = tag_cnt.get(t, 0) + 1
    if tag_cnt:
        print()
        print("   ── 依 tags 分佈（多標籤，總和 ≥ 段數）──")
        for t in sorted(tag_cnt):
            print(f"   {t:12} {tag_cnt[t]:3}")


def warn_blank_durations(rows: list[dict], threshold: float = 0.05) -> None:
    """掃描後檢查 duration 空白率，過高就大聲警告（多半是 env 缺 soundfile）。

    duration_sec 空白 → build_finetune_dataset 寫進 jsonl 的 source_len 變 0
    → 影響 FunASR 長度分桶/排序，是訓練 metadata 錯誤而非單純顯示問題。
    """
    blank = [r for r in rows if not str(r["duration_sec"]).strip()]
    if not rows or not blank:
        return
    ratio = len(blank) / len(rows)
    if ratio <= threshold:
        print(f"\nℹ️  {len(blank)} 段 duration 空白（{ratio*100:.1f}%）— 個別檔讀取失敗，可單獨檢查")
        return
    fmt = {}
    for r in blank:
        fmt[r["audio_format"]] = fmt.get(r["audio_format"], 0) + 1
    print()
    print("⚠️ " + "─" * 56)
    print(f"⚠️  {len(blank)}/{len(rows)} 段 duration 空白（{ratio*100:.0f}%）— 多半是 env 缺 soundfile")
    print(f"    空白格式分布: {fmt}")
    print(f"    後果: finetune jsonl 的 source_len 會變 0，影響 FunASR 長度分桶。")
    print(f"    對策: 改用含 soundfile 的 env 重建後再進 build_finetune_dataset。")
    print("⚠️ " + "─" * 56)


def list_missing(rows: list[dict]) -> None:
    """列出尚未配對 GT 的音檔"""
    missing = [r for r in rows if r["has_gt"] == "N"]
    if not missing:
        print("✅ 所有音檔都已有對應 GT")
        return
    print(f"⚠️  尚有 {len(missing)} 個音檔未標註 GT：")
    for r in missing:
        print(f"   - {r['audio_file']}")
        print(f"     需建立: {r['gt_file']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio-dir", default=str(DEFAULT_DATASET_DIR / "audio"))
    p.add_argument("--gt-dir", default=str(DEFAULT_DATASET_DIR / "ground_truth"))
    p.add_argument("--output", default=str(DEFAULT_DATASET_DIR / "manifest.csv"))
    p.add_argument("--event-types", default=str(DEFAULT_EVENT_TYPES_CSV),
                   help="event_type/tags sidecar CSV（id,event_type,tags）")
    p.add_argument("--list-missing", action="store_true",
                   help="只列出尚未配對 GT 的音檔，不寫 manifest")
    args = p.parse_args()

    audio_dir = Path(args.audio_dir)
    gt_dir = Path(args.gt_dir)
    output = Path(args.output)

    print(f"🔍 掃描黃金語料集")
    print(f"   audio dir: {audio_dir}")
    print(f"   gt dir:    {gt_dir}")
    print()

    if not soundfile_available():
        print("⚠️  未偵測到 soundfile —— 多數 wav / 全部 mp3 的時長會留空白，")
        print("    連帶 finetune jsonl 的 source_len 會變 0（影響 FunASR 長度分桶）。")
        print("    請改用含 soundfile 的 env 重建（見 requirements.txt）。")
        print()

    existing_notes = load_existing_notes(output)
    event_types = load_event_types(Path(args.event_types))
    if event_types:
        print(f"   event_types sidecar: {len(event_types)} 筆覆寫（{args.event_types}）")
    rows = scan_dataset(audio_dir, gt_dir, existing_notes, event_types)

    if args.list_missing:
        list_missing(rows)
        return

    write_manifest(rows, output)
    print(f"✅ Manifest 已產生: {output}")
    print(f"   共 {len(rows)} 筆記錄")

    print_stats(rows)
    warn_blank_durations(rows)

    # 列出未標註的
    missing = [r for r in rows if r["has_gt"] == "N"]
    if missing:
        print()
        print(f"⚠️  尚有 {len(missing)} 個音檔未標註 GT")
        print(f"   執行 `python3 scripts/build_golden_manifest.py --list-missing` 查看清單")


if __name__ == "__main__":
    main()
