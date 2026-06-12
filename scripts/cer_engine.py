#!/usr/bin/env python3
"""
CER / WER 計算引擎（字元錯誤率 / 詞錯誤率 / 準確率評測）
==========================================================
提供：
  - 文字前處理正規化
  - CER（字元錯誤率）：優先使用 jiwer，fallback 用純 Python Levenshtein DP
  - WER（詞錯誤率）  ：jieba 分詞 + jiwer，fallback 用純 Python Levenshtein DP
  - 差異分析 HTML（字元級高亮顯示）
  - 逐檔與整體批次評測（同時輸出 CER 與 WER）

使用方式（獨立測試）：
    python scripts/cer_engine.py --ref ground_truth/sample.txt --hyp asr_output/sample.txt
"""

import csv
import re
import difflib
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ── 可選依賴 ─────────────────────────────────────────────────────────────────
try:
    import jiwer
    JIWER_OK = True
except ImportError:
    JIWER_OK = False

try:
    import jieba
    jieba.setLogLevel(60)   # 關閉 jieba 初始化 log
    JIEBA_OK = True
except ImportError:
    JIEBA_OK = False

try:
    # 與 batch_eval.normalize_for_cer 對齊：簡繁統一（s2twp），否則 lab UI 會把
    # 模型輸出的簡體（确/换/没…）誤計為錯誤，與批次評測數字不一致。
    from opencc import OpenCC
    _CC = OpenCC("s2twp")
except Exception:
    _CC = None


# ============================================================================
# 檔案讀取（支援 .txt 與 .csv）
# ============================================================================

# CSV 欄位名稱（與 ASR 下載格式一致）
_CSV_TEXT_COLS = ["辨識文字", "transcript", "text", "內容"]


def read_transcript_file(filepath: Path) -> str:
    """
    讀取逐字稿文字，同時支援 .txt 與 .csv 格式。

    CSV 規則（與辨識結果下載格式相同）：
      - 自動偵測 UTF-8 / UTF-8-BOM 編碼
      - 依序嘗試欄位：辨識文字 → transcript → text → 內容
      - 將所有列的文字，依序號（若有）排序後，以換行符號合併成一段
    TXT 規則：
      - 讀取全文，去除首尾空白
    """
    suffix = filepath.suffix.lower()

    if suffix == ".csv":
        return _read_csv_transcript(filepath)
    else:
        return filepath.read_text(encoding="utf-8-sig").strip()


def _read_csv_transcript(filepath: Path) -> str:
    """從 CSV 提取辨識文字欄位，合併為完整文字。"""
    # 嘗試 utf-8-sig（含 BOM），再試 utf-8
    for enc in ("utf-8-sig", "utf-8", "cp950"):
        try:
            text = filepath.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return ""

    reader = csv.DictReader(text.splitlines())
    headers = reader.fieldnames or []

    # 找出文字欄位名稱
    text_col = next((c for c in _CSV_TEXT_COLS if c in headers), None)
    if text_col is None:
        # 找不到已知欄位，取第三欄（index=2）作為 fallback
        rows_raw = list(csv.reader(text.splitlines()))
        if len(rows_raw) > 1:
            col_idx = 2 if len(rows_raw[0]) > 2 else 0
            return "\n".join(
                row[col_idx].strip()
                for row in rows_raw[1:]
                if len(row) > col_idx and row[col_idx].strip()
            )
        return ""

    # 找序號欄（用於排序）
    seq_col = next((c for c in ["序號", "id", "index"] if c in headers), None)

    rows = list(reader)
    if seq_col:
        try:
            rows.sort(key=lambda r: int(r.get(seq_col, 0) or 0))
        except (ValueError, TypeError):
            pass

    lines = [r[text_col].strip() for r in rows if r.get(text_col, "").strip()]
    return "\n".join(lines)


# ============================================================================
# 文字前處理
# ============================================================================

def normalize_text(text: str) -> str:
    """
    評測用正規化：
    1. 移除行首講者標記（B: / H: / ? 等）——GT 標註，非語音內容
    2. 移除方括號標註（[HH:MM:SS] 時間戳、[noise] 等）與 STT 講者標記【…】
    3. 全形數字 → 半形
    4. 移除標點符號與空白（保留中文字、英數字）
    5. 英文大寫 → 小寫

    註：講者/標註剝除規則與 experiments/llm_correction_poc/batch_eval.py 的
    normalize_for_cer 對齊，確保 lab UI 與批次評測 CER 一致。
    """
    # 移除行首講者標記（B: / H: / G: / ? 等），避免標記字母被當成漏字誤計
    text = re.sub(r"^\s*[A-Za-z?]:\s*", "", text, flags=re.MULTILINE)
    # 移除方括號標註（含時間戳 [12:34]、[noise]、[unclear] 等）
    text = re.sub(r"\[[^\]]*\]", "", text)
    # 移除 STT 講者標記【講者X | 時間】
    text = re.sub(r"【[^】]*】", "", text)
    # 全形數字轉半形
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # 全形英文轉半形
    text = text.translate(str.maketrans(
        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ))
    # 移除標點與空白（保留中文字 \u4e00-\u9fff 及英數字）
    text = re.sub(r"[^\u4e00-\u9fff\w]", "", text)
    # 英文小寫
    text = text.lower()
    # 簡繁統一（與 batch_eval 對齊；評分時 ref/hyp 都套，繁簡差異不計為錯誤）
    if _CC is not None:
        text = _CC.convert(text)
    return text


# ============================================================================
# CER 計算
# ============================================================================

def _levenshtein_edits(ref: str, hyp: str) -> Tuple[int, int, int]:
    """
    純 Python 真 Levenshtein DP 計算字元級最小編輯操作數。
    回傳 (substitutions, deletions, insertions)

    注意：不可用 difflib.SequenceMatcher 近似——它找的是「最長連續相同
    區塊」而非最小編輯距離，對吵雜 ASR 文本會對齊崩潰、嚴重高估錯誤
    （實測北屯批次整體灌水 +13pp，個別檔案把 ~37% 算成 100%）。
    複雜度 O(len(ref)×len(hyp))，數千字內夠快；更長文本請裝 jiwer。
    """
    n, m = len(ref), len(hyp)
    # prev[j] = (cost, sub, del, ins)；同 cost 時偏好替換（與 jiwer 對齊習慣一致）
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for i in range(1, n + 1):
        ri = ref[i - 1]
        cur = [(i, 0, i, 0)] + [(0, 0, 0, 0)] * m
        for j in range(1, m + 1):
            dc, ds, dd, di = prev[j - 1]
            if ri == hyp[j - 1]:
                # 字元相同時走對角線必不劣，直接採用
                cur[j] = (dc, ds, dd, di)
                continue
            best = (dc + 1, ds + 1, dd, di)          # substitution
            uc, us, ud, ui = prev[j]                  # deletion（ref 多字）
            if uc + 1 < best[0]:
                best = (uc + 1, us, ud + 1, ui)
            lc, ls, ld, li = cur[j - 1]               # insertion（hyp 多字）
            if lc + 1 < best[0]:
                best = (lc + 1, ls, ld, li + 1)
            cur[j] = best
        prev = cur
    _, sub, del_, ins = prev[m]
    return sub, del_, ins


def calculate_cer(reference: str, hypothesis: str) -> Dict:
    """
    計算 CER（字元錯誤率）。
    優先使用 jiwer（更精確的 Levenshtein 對齊），
    若未安裝則 fallback 至純 Python Levenshtein DP。

    回傳 dict：
      cer       : float  0.0~1.0
      accuracy  : float  0.0~1.0  (= 1 - cer)
      n_ref     : int    reference 字元數
      sub       : int    替換錯誤數
      del_      : int    刪除錯誤數
      ins       : int    插入錯誤數
      n_errors  : int    sub + del_ + ins
      engine    : str    "jiwer" or "levenshtein"
    """
    ref_norm = normalize_text(reference)
    hyp_norm = normalize_text(hypothesis)
    n = len(ref_norm)

    if n == 0:
        return {
            "cer": 0.0, "accuracy": 1.0, "n_ref": 0,
            "sub": 0, "del_": 0, "ins": 0, "n_errors": 0, "engine": "none"
        }

    if JIWER_OK:
        try:
            # jiwer.process_characters 直接逐字元對齊，給出精確 sub/del/ins 分解。
            # 注意：不可用 " ".join(list(...)) 把字元用空格隔開——那會讓每個
            # 插入/刪除多算一個空格 token（del/ins 約 2 倍），嚴重灌水 CER。
            out = jiwer.process_characters(ref_norm, hyp_norm)
            sub  = out.substitutions
            del_ = out.deletions
            ins  = out.insertions
            engine = "jiwer"
        except Exception:
            sub, del_, ins = _levenshtein_edits(ref_norm, hyp_norm)
            engine = "levenshtein"
    else:
        sub, del_, ins = _levenshtein_edits(ref_norm, hyp_norm)
        engine = "levenshtein"

    n_errors = sub + del_ + ins
    cer      = n_errors / n
    return {
        "cer":      round(min(cer, 1.0), 6),
        "accuracy": round(max(0.0, 1.0 - cer), 6),
        "n_ref":    n,
        "sub":      sub,
        "del_":     del_,
        "ins":      ins,
        "n_errors": n_errors,
        "engine":   engine,
    }


# ============================================================================
# WER（詞錯誤率）計算
# ============================================================================

def _tokenize(text: str) -> List[str]:
    """
    將正規化後的文字分詞。
    優先使用 jieba（中文精確模式），未安裝時依空白切分（英文適用）。
    """
    norm = normalize_text(text)
    if not norm:
        return []
    if JIEBA_OK:
        return [w for w in jieba.cut(norm) if w.strip()]
    # fallback：按字元切（效果等同 CER）
    return list(norm)


def calculate_wer(reference: str, hypothesis: str) -> Dict:
    """
    計算 WER（詞錯誤率）。
    以 jieba 分詞後用 jiwer.process_words() 計算；
    未安裝 jieba 時退回字元級（等同 CER）。

    回傳 dict：
      wer       : float  0.0~1.0
      accuracy  : float  0.0~1.0  (= 1 - wer)
      n_ref     : int    reference 詞數
      sub       : int    替換錯誤數
      del_      : int    刪除錯誤數
      ins       : int    插入錯誤數
      n_errors  : int    sub + del_ + ins
      engine    : str    "jiwer+jieba" / "jiwer" / "levenshtein"
      tokenizer : str    "jieba" / "char"
    """
    ref_tokens = _tokenize(reference)
    hyp_tokens = _tokenize(hypothesis)
    n = len(ref_tokens)
    tokenizer = "jieba" if JIEBA_OK else "char"

    if n == 0:
        return {
            "wer": 0.0, "accuracy": 1.0, "n_ref": 0,
            "sub": 0, "del_": 0, "ins": 0, "n_errors": 0,
            "engine": "none", "tokenizer": tokenizer,
        }

    if JIWER_OK:
        try:
            out = jiwer.process_words(
                " ".join(ref_tokens),
                " ".join(hyp_tokens),
            )
            sub  = out.substitutions
            del_ = out.deletions
            ins  = out.insertions
            engine = "jiwer+jieba" if JIEBA_OK else "jiwer"
        except Exception:
            sub, del_, ins = _levenshtein_edits(ref_tokens, hyp_tokens)
            engine = "levenshtein"
    else:
        sub, del_, ins = _levenshtein_edits(ref_tokens, hyp_tokens)
        engine = "levenshtein"

    n_errors = sub + del_ + ins
    wer      = n_errors / n
    return {
        "wer":       round(min(wer, 1.0), 6),
        "accuracy":  round(max(0.0, 1.0 - wer), 6),
        "n_ref":     n,
        "sub":       sub,
        "del_":      del_,
        "ins":       ins,
        "n_errors":  n_errors,
        "engine":    engine,
        "tokenizer": tokenizer,
    }


# ============================================================================
# 差異分析 HTML
# ============================================================================

_STYLE_SUB = "background:#ff6b6b; color:#fff; border-radius:3px; padding:0 2px;"
_STYLE_DEL = "background:#ffa07a; color:#fff; border-radius:3px; padding:0 2px;"
_STYLE_INS = "background:#87ceeb; color:#000; border-radius:3px; padding:0 2px;"


def build_diff_html(reference: str, hypothesis: str) -> str:
    """
    生成字元級差異對照 HTML（雙欄：標準文稿 | 辨識結果）。

    顏色規則：
      🔴 紅色（substitute）：替換錯誤，兩欄都標記
      🟠 橘色（delete）    ：reference 有、hypothesis 沒有 → 只在左欄標記
      🔵 藍色（insert）    ：reference 沒有、hypothesis 多出來 → 只在右欄標記
    """
    ref_norm = normalize_text(reference)
    hyp_norm = normalize_text(hypothesis)

    matcher = difflib.SequenceMatcher(None, ref_norm, hyp_norm, autojunk=False)

    ref_parts: List[str] = []
    hyp_parts: List[str] = []

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        ref_chunk = _esc(ref_norm[i1:i2])
        hyp_chunk = _esc(hyp_norm[j1:j2])
        if tag == "equal":
            ref_parts.append(ref_chunk)
            hyp_parts.append(hyp_chunk)
        elif tag == "replace":
            ref_parts.append(f'<span style="{_STYLE_SUB}">{ref_chunk}</span>')
            hyp_parts.append(f'<span style="{_STYLE_SUB}">{hyp_chunk}</span>')
        elif tag == "delete":
            ref_parts.append(f'<span style="{_STYLE_DEL}">{ref_chunk}</span>')
        elif tag == "insert":
            hyp_parts.append(f'<span style="{_STYLE_INS}">{hyp_chunk}</span>')

    ref_html = "".join(ref_parts)
    hyp_html = "".join(hyp_parts)

    legend = (
        '<div style="font-size:0.82em; color:#888; margin-bottom:8px;">'
        '<span style="background:#ff6b6b; color:#fff; border-radius:3px; padding:0 4px;">替換</span> '
        '<span style="background:#ffa07a; color:#fff; border-radius:3px; padding:0 4px;">多餘刪除</span> '
        '<span style="background:#87ceeb; color:#000; border-radius:3px; padding:0 4px;">插入補漏</span>'
        '</div>'
    )
    grid = (
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; '
        'font-family:monospace; font-size:0.95em; line-height:1.9; word-break:break-all;">'
        f'<div><b>📄 標準文稿</b><br>{ref_html}</div>'
        f'<div><b>🎙️ 辨識結果</b><br>{hyp_html}</div>'
        '</div>'
    )
    return legend + grid


# ============================================================================
# 批次評測
# ============================================================================

def evaluate_case(
    ground_truth_dir: Path,
    asr_output_dir:   Path,
) -> Dict:
    """
    逐檔計算 CER 與 WER，彙整整體統計。

    ground_truth_dir : experiments/{case}/ground_truth/
    asr_output_dir   : experiments/{case}/asr_output/

    回傳：
    {
      "per_file": [
          {
            "stem": str,
            "gt_text": str, "asr_text": str,
            # CER
            "cer": float, "accuracy": float,
            "n_ref": int, "sub": int, "del_": int, "ins": int, "n_errors": int,
            # WER
            "wer": float, "wer_accuracy": float,
            "n_words": int, "wer_sub": int, "wer_del": int, "wer_ins": int,
            "diff_html": str,
            "matched": bool,
          }, ...
      ],
      "overall": {
          # CER
          "mean_cer": float, "mean_accuracy": float,
          "total_chars": int, "total_errors": int,
          "micro_cer": float, "micro_accuracy": float,
          # WER
          "mean_wer": float, "mean_wer_accuracy": float,
          "total_words": int, "total_wer_errors": int,
          "micro_wer": float, "micro_wer_accuracy": float,
          "wer_tokenizer": str,
          "n_files_matched": int, "n_files_total": int,
      }
    }
    """
    gt_files = sorted(
        f for f in ground_truth_dir.iterdir()
        if f.suffix.lower() in {".txt", ".csv"}
    )
    per_file_results = []

    for gt_file in gt_files:
        stem    = gt_file.stem
        gt_text = read_transcript_file(gt_file)

        asr_file = None
        for ext in (".csv", ".txt"):
            candidate = asr_output_dir / f"{stem}{ext}"
            if candidate.exists():
                asr_file = candidate
                break

        if asr_file is None:
            n_chars = len(normalize_text(gt_text))
            n_words = len(_tokenize(gt_text))
            per_file_results.append({
                "stem": stem, "gt_text": gt_text, "asr_text": "",
                "cer": 1.0, "accuracy": 0.0,
                "n_ref": n_chars,
                "sub": 0, "del_": n_chars, "ins": 0, "n_errors": n_chars,
                "wer": 1.0, "wer_accuracy": 0.0,
                "n_words": n_words,
                "wer_sub": 0, "wer_del": n_words, "wer_ins": 0,
                "diff_html": (
                    f"<span style='color:#f88;'>⚠️ 找不到辨識結果：{stem}.csv / {stem}.txt</span>"
                ),
                "matched": False,
            })
            continue

        asr_text  = read_transcript_file(asr_file)
        cer_info  = calculate_cer(gt_text, asr_text)
        wer_info  = calculate_wer(gt_text, asr_text)
        diff_html = build_diff_html(gt_text, asr_text)

        per_file_results.append({
            "stem":         stem,
            "gt_text":      gt_text,
            "asr_text":     asr_text,
            # CER
            "cer":          cer_info["cer"],
            "accuracy":     cer_info["accuracy"],
            "n_ref":        cer_info["n_ref"],
            "sub":          cer_info["sub"],
            "del_":         cer_info["del_"],
            "ins":          cer_info["ins"],
            "n_errors":     cer_info["n_errors"],
            # WER
            "wer":          wer_info["wer"],
            "wer_accuracy": wer_info["accuracy"],
            "n_words":      wer_info["n_ref"],
            "wer_sub":      wer_info["sub"],
            "wer_del":      wer_info["del_"],
            "wer_ins":      wer_info["ins"],
            "wer_tokenizer": wer_info["tokenizer"],
            "diff_html":    diff_html,
            "matched":      True,
        })

    # 整體統計
    matched   = [r for r in per_file_results if r["matched"]]
    n_total   = len(per_file_results)
    n_matched = len(matched)

    if matched:
        # CER
        mean_cer      = sum(r["cer"]      for r in matched) / n_matched
        mean_accuracy = sum(r["accuracy"] for r in matched) / n_matched
        total_chars   = sum(r["n_ref"]    for r in matched)
        total_errors  = sum(r["n_errors"] for r in matched)
        micro_cer     = total_errors / total_chars if total_chars > 0 else 0.0
        # WER
        mean_wer          = sum(r["wer"]          for r in matched) / n_matched
        mean_wer_accuracy = sum(r["wer_accuracy"] for r in matched) / n_matched
        total_words       = sum(r["n_words"]  for r in matched)
        total_wer_errors  = sum(r["wer_sub"] + r["wer_del"] + r["wer_ins"] for r in matched)
        micro_wer         = total_wer_errors / total_words if total_words > 0 else 0.0
        wer_tokenizer     = matched[0].get("wer_tokenizer", "char")
    else:
        mean_cer = mean_accuracy = micro_cer = 0.0
        mean_wer = mean_wer_accuracy = micro_wer = 0.0
        total_chars = total_errors = total_words = total_wer_errors = 0
        wer_tokenizer = "char"

    overall = {
        # CER
        "mean_cer":           round(mean_cer, 6),
        "mean_accuracy":      round(mean_accuracy, 6),
        "total_chars":        total_chars,
        "total_errors":       total_errors,
        "micro_cer":          round(micro_cer, 6),
        "micro_accuracy":     round(max(0.0, 1.0 - micro_cer), 6),
        # WER
        "mean_wer":           round(mean_wer, 6),
        "mean_wer_accuracy":  round(mean_wer_accuracy, 6),
        "total_words":        total_words,
        "total_wer_errors":   total_wer_errors,
        "micro_wer":          round(micro_wer, 6),
        "micro_wer_accuracy": round(max(0.0, 1.0 - micro_wer), 6),
        "wer_tokenizer":      wer_tokenizer,
        "n_files_matched":    n_matched,
        "n_files_total":      n_total,
    }

    return {"per_file": per_file_results, "overall": overall}


def generate_text_report(case_name: str, results: Dict, meta: Optional[Dict] = None) -> str:
    """
    生成人可讀的文字評測報告。

    meta 可包含：
      mode        : "audio_asr"（語音辨識模式）或 "text_compare"（純文稿比對模式）
      model_type  : e.g., "google_stt" / "gemini" / "whisper"
      sub_model   : e.g., "chirp_3" / "gemini-2.5-flash"
      timestamp   : 評測時間字串
      gt_filename : 標準文稿檔名（純文稿比對模式）
      asr_filename: 辨識結果檔名（純文稿比對模式）
    """
    ov   = results["overall"]
    meta = meta or {}

    # ── 模式說明文字 ──────────────────────────────────────────────────────
    mode_label = {
        "audio_asr":    "語音辨識 + 準確率計算",
        "text_compare": "純文稿比對",
    }.get(meta.get("mode", ""), "不明")

    model_label   = meta.get("model_label", "—")
    sub_model     = meta.get("sub_model",   "—")
    eval_ts       = meta.get("timestamp",   "—")

    lines = [
        "=" * 60,
        "語音辨識準確率評測報告",
        f"案例：{case_name}",
        "=" * 60,
        "",
        "【評測資訊】",
        f"  評測模式   ：{mode_label}",
    ]

    if meta.get("mode") == "audio_asr":
        lines += [
            f"  辨識模型   ：{model_label}",
            f"  子模型     ：{sub_model}",
        ]
    elif meta.get("mode") == "text_compare":
        lines += [
            f"  標準文稿   ：{meta.get('gt_filename', '—')}",
            f"  辨識文稿   ：{meta.get('asr_filename', '—')}",
        ]

    tk = ov.get("wer_tokenizer", "jieba")
    lines += [
        f"  評測時間   ：{eval_ts}",
        "",
        "【整體統計】",
        f"  比對檔案數   ：{ov['n_files_matched']} / {ov['n_files_total']}",
        "",
        "  ─── CER（字元錯誤率）───────────────────",
        f"  整體準確率   ：{ov['micro_accuracy']:.1%}  (micro，加權)",
        f"  平均準確率   ：{ov['mean_accuracy']:.1%}  (macro，各檔平均)",
        f"  整體 CER     ：{ov['micro_cer']:.1%}",
        f"  平均 CER     ：{ov['mean_cer']:.1%}",
        f"  總字元數     ：{ov['total_chars']}",
        f"  總字元錯誤數 ：{ov['total_errors']}",
        "",
        f"  ─── WER（詞錯誤率，分詞器：{tk}）─────",
        f"  整體 WER 準確率：{ov.get('micro_wer_accuracy', 0):.1%}  (micro，加權)",
        f"  平均 WER 準確率：{ov.get('mean_wer_accuracy', 0):.1%}  (macro，各檔平均)",
        f"  整體 WER       ：{ov.get('micro_wer', 0):.1%}",
        f"  平均 WER       ：{ov.get('mean_wer', 0):.1%}",
        f"  總詞數         ：{ov.get('total_words', 0)}",
        f"  總詞錯誤數     ：{ov.get('total_wer_errors', 0)}",
        "",
        "─" * 60,
        "【逐檔明細】",
        "",
    ]
    for r in results["per_file"]:
        if r["matched"]:
            lines.append(
                f"  [{r['accuracy']:.1%}]  {r['stem']}"
                f"　CER={r['cer']:.1%}  WER={r.get('wer', 0):.1%}"
                f"  字元N={r['n_ref']} 詞N={r.get('n_words',0)}"
                f"  替換={r['sub']} 刪除={r['del_']} 插入={r['ins']}"
            )
            lines.append(f"    標準：{r['gt_text'][:80]}{'...' if len(r['gt_text'])>80 else ''}")
            lines.append(f"    辨識：{r['asr_text'][:80]}{'...' if len(r['asr_text'])>80 else ''}")
            lines.append("")
        else:
            lines.append(f"  [缺失] {r['stem']}（找不到對應辨識結果）")
            lines.append("")
    return "\n".join(lines)


def compare_two_texts(
    gt_text: str,
    asr_text: str,
    gt_name: str = "標準文稿",
    asr_name: str = "辨識結果",
) -> Dict:
    """
    直接比對兩段文字（純文稿比對模式）。

    回傳與 evaluate_case() 相容的結構：
    { "per_file": [...], "overall": {...} }
    """
    cer_info  = calculate_cer(gt_text, asr_text)
    wer_info  = calculate_wer(gt_text, asr_text)
    diff_html = build_diff_html(gt_text, asr_text)

    per_file = [{
        "stem":         asr_name,
        "gt_text":      gt_text,
        "asr_text":     asr_text,
        # CER
        "cer":          cer_info["cer"],
        "accuracy":     cer_info["accuracy"],
        "n_ref":        cer_info["n_ref"],
        "sub":          cer_info["sub"],
        "del_":         cer_info["del_"],
        "ins":          cer_info["ins"],
        "n_errors":     cer_info["n_errors"],
        # WER
        "wer":          wer_info["wer"],
        "wer_accuracy": wer_info["accuracy"],
        "n_words":      wer_info["n_ref"],
        "wer_sub":      wer_info["sub"],
        "wer_del":      wer_info["del_"],
        "wer_ins":      wer_info["ins"],
        "wer_tokenizer": wer_info["tokenizer"],
        "diff_html":    diff_html,
        "matched":      True,
    }]

    total_wer_errors = wer_info["sub"] + wer_info["del_"] + wer_info["ins"]
    overall = {
        # CER
        "mean_cer":           cer_info["cer"],
        "mean_accuracy":      cer_info["accuracy"],
        "total_chars":        cer_info["n_ref"],
        "total_errors":       cer_info["n_errors"],
        "micro_cer":          cer_info["cer"],
        "micro_accuracy":     cer_info["accuracy"],
        # WER
        "mean_wer":           wer_info["wer"],
        "mean_wer_accuracy":  wer_info["accuracy"],
        "total_words":        wer_info["n_ref"],
        "total_wer_errors":   total_wer_errors,
        "micro_wer":          wer_info["wer"],
        "micro_wer_accuracy": wer_info["accuracy"],
        "wer_tokenizer":      wer_info["tokenizer"],
        "n_files_matched":    1,
        "n_files_total":      1,
    }

    return {"per_file": per_file, "overall": overall}


# ============================================================================
# 批次純文稿比對（多對多配對 + 整體統計）
# ============================================================================

def match_stems_by_prefix(
    gt_stems:  List[str],
    asr_stems: List[str],
) -> Dict:
    """
    配對 GT 與 ASR 檔名：ASR stem 以 GT stem 為前綴（case-insensitive）。

    規則：
      - 對每個 GT stem，找出所有以它開頭的 ASR stem
      - 若有多個候選，取 stem 最短的（最接近 GT 原始命名）
      - 每個 ASR stem 至多被使用一次（先到先得）

    典型命名範例：
      GT  : 260603_北屯機廠號誌故障_正線_072318
      ASR : 260603_北屯機廠號誌故障_正線_072318_senseVoice(4CER)
      → ASR stem 以 GT stem 開頭 → 配對成功

    Returns dict：
      matched       : List[Tuple[str, str]]  [(gt_stem, asr_stem), ...]
      unmatched_gt  : List[str]              找不到 ASR 的 GT stems
      unmatched_asr : List[str]              沒被任何 GT 配到的 ASR stems
    """
    matched:       List[Tuple[str, str]] = []
    used_asr:      set                   = set()
    unmatched_gt:  List[str]             = []

    for gt_stem in gt_stems:
        gt_lower = gt_stem.lower()
        candidates = [
            a for a in asr_stems
            if a.lower().startswith(gt_lower) and a not in used_asr
        ]
        if candidates:
            best = min(candidates, key=len)   # 最短 stem = 最接近 GT 命名
            matched.append((gt_stem, best))
            used_asr.add(best)
        else:
            unmatched_gt.append(gt_stem)

    unmatched_asr = [a for a in asr_stems if a not in used_asr]

    return {
        "matched":       matched,
        "unmatched_gt":  unmatched_gt,
        "unmatched_asr": unmatched_asr,
    }


def compare_multiple_texts(
    matched_pairs: List[Tuple[str, str, str, str]],
) -> Dict:
    """
    批次比對多對文稿，回傳與 evaluate_case() / compare_two_texts() 相容的結構。

    matched_pairs: [(gt_text, asr_text, gt_name, asr_name), ...]
      - gt_text  : 標準文稿全文
      - asr_text : 辨識結果全文
      - gt_name  : 顯示用 GT 檔名（stem）
      - asr_name : 顯示用 ASR 檔名（stem），用作 per_file["stem"]

    Returns：
      { "per_file": [...], "overall": {...} }
      格式與 evaluate_case() 完全相容，可直接傳入 _render_eval_results()。
    """
    per_file: List[Dict] = []

    for gt_text, asr_text, gt_name, asr_name in matched_pairs:
        cer_info  = calculate_cer(gt_text, asr_text)
        wer_info  = calculate_wer(gt_text, asr_text)
        diff_html = build_diff_html(gt_text, asr_text)

        per_file.append({
            "stem":          asr_name,
            "gt_name":       gt_name,
            "gt_text":       gt_text,
            "asr_text":      asr_text,
            # CER
            "cer":           cer_info["cer"],
            "accuracy":      cer_info["accuracy"],
            "n_ref":         cer_info["n_ref"],
            "sub":           cer_info["sub"],
            "del_":          cer_info["del_"],
            "ins":           cer_info["ins"],
            "n_errors":      cer_info["n_errors"],
            # WER
            "wer":           wer_info["wer"],
            "wer_accuracy":  wer_info["accuracy"],
            "n_words":       wer_info["n_ref"],
            "wer_sub":       wer_info["sub"],
            "wer_del":       wer_info["del_"],
            "wer_ins":       wer_info["ins"],
            "wer_tokenizer": wer_info["tokenizer"],
            "diff_html":     diff_html,
            "matched":       True,
        })

    n_matched = len(per_file)
    n_total   = n_matched   # compare_multiple_texts 只處理已配對對；未配對由 UI 層排除

    if per_file:
        mean_cer      = sum(r["cer"]      for r in per_file) / n_matched
        mean_accuracy = sum(r["accuracy"] for r in per_file) / n_matched
        total_chars   = sum(r["n_ref"]    for r in per_file)
        total_errors  = sum(r["n_errors"] for r in per_file)
        micro_cer     = total_errors / total_chars if total_chars > 0 else 0.0

        mean_wer          = sum(r["wer"]          for r in per_file) / n_matched
        mean_wer_accuracy = sum(r["wer_accuracy"] for r in per_file) / n_matched
        total_words       = sum(r["n_words"]  for r in per_file)
        total_wer_errors  = sum(
            r["wer_sub"] + r["wer_del"] + r["wer_ins"] for r in per_file
        )
        micro_wer     = total_wer_errors / total_words if total_words > 0 else 0.0
        wer_tokenizer = per_file[0].get("wer_tokenizer", "char")
    else:
        mean_cer = mean_accuracy = micro_cer = 0.0
        mean_wer = mean_wer_accuracy = micro_wer = 0.0
        total_chars = total_errors = total_words = total_wer_errors = 0
        wer_tokenizer = "char"

    overall = {
        "mean_cer":           mean_cer,
        "mean_accuracy":      mean_accuracy,
        "total_chars":        total_chars,
        "total_errors":       total_errors,
        "micro_cer":          micro_cer,
        "micro_accuracy":     max(0.0, 1.0 - micro_cer),
        "mean_wer":           mean_wer,
        "mean_wer_accuracy":  mean_wer_accuracy,
        "total_words":        total_words,
        "total_wer_errors":   total_wer_errors,
        "micro_wer":          micro_wer,
        "micro_wer_accuracy": max(0.0, 1.0 - micro_wer),
        "wer_tokenizer":      wer_tokenizer,
        "n_files_matched":    n_matched,
        "n_files_total":      n_total,
    }

    return {"per_file": per_file, "overall": overall}


# ============================================================================
# CLI 測試入口
# ============================================================================
if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="CER 評測引擎 CLI")
    parser.add_argument("--ref", required=True, help="標準文稿 .txt")
    parser.add_argument("--hyp", required=True, help="辨識結果 .txt")
    args = parser.parse_args()

    ref_text = Path(args.ref).read_text(encoding="utf-8").strip()
    hyp_text = Path(args.hyp).read_text(encoding="utf-8").strip()

    result = calculate_cer(ref_text, hyp_text)
    print(f"\n{'='*50}")
    print(f"引擎         : {result['engine']}")
    print(f"標準字元數   : {result['n_ref']}")
    print(f"CER          : {result['cer']:.2%}")
    print(f"準確率       : {result['accuracy']:.2%}")
    print(f"替換 / 刪除 / 插入 : {result['sub']} / {result['del_']} / {result['ins']}")
    print(f"{'='*50}\n")
