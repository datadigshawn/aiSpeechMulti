#!/usr/bin/env python3
"""
即時辨識結果 CER 評測工具
==========================
比較「即時辨識輸出」與「官方文稿」，計算字元錯誤率（CER）與錯誤分析。

使用方式：
    python scripts/realtime_cer_eval.py \
        --hyp  <辨識結果.txt>  \
        --ref  <官方文稿.txt>  \
        [--output <報告輸出.txt>]

範例：
    python scripts/realtime_cer_eval.py \
        --hyp  ~/Downloads/realtime_20260317_113152.txt \
        --ref  experiments/reference/broadcast_20260317.txt
"""

import re
import sys
import argparse
from pathlib import Path

# ── 可選依賴 ─────────────────────────────────────────────────────────────────
try:
    import jiwer
    JIWER_OK = True
except ImportError:
    JIWER_OK = False
    print("[警告] jiwer 未安裝，請先執行：pip install jiwer")
    print("       安裝後重新執行本腳本。")
    sys.exit(1)

try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")   # 繁→簡，僅用於字元正規化比對（不改變輸出）
    OPENCC_OK = True
except ImportError:
    OPENCC_OK = False


# ============================================================================
# 文字前處理
# ============================================================================

def strip_timestamps(text: str) -> str:
    """移除即時辨識輸出的時間戳記，例如 [11:19:50] 或 🔍 診斷提示 開頭的行。"""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳過診斷提示行
        if line.startswith("🔍"):
            continue
        # 移除 [HH:MM:SS] 前綴
        line = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line)
        if line:
            lines.append(line)
    return " ".join(lines)


def normalize(text: str) -> str:
    """
    評測用正規化：
    1. 移除標點符號（中英文）
    2. 移除空白
    3. 全形數字 → 半形
    4. 英文大寫 → 小寫
    （不做簡繁轉換，保留原始字元以反映真實辨識狀況）
    """
    # 全形數字轉半形
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    # 移除標點（保留中文字、英數字）
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    # 英文小寫
    text = text.lower()
    return text


def text_to_chars(text: str) -> str:
    """將文字轉為以空格分隔的字元序列（供 jiwer 計算 CER）。"""
    return " ".join(list(text))


# ============================================================================
# 錯誤分析
# ============================================================================

def find_error_examples(ref_chars: list, hyp_chars: list, max_examples: int = 20) -> list:
    """
    利用 jiwer 的對齊結果找出常見錯誤字元。
    回傳 [(ref_char, hyp_char, type), ...] 的錯誤列表。
    """
    errors = []
    try:
        out = jiwer.process_characters(
            " ".join(ref_chars),
            " ".join(hyp_chars),
        )
        for chunk in out.alignments[0]:
            if chunk.type == "substitute":
                for i, j in zip(
                    range(chunk.ref_start_idx, chunk.ref_end_idx),
                    range(chunk.hyp_start_idx, chunk.hyp_end_idx),
                ):
                    if i < len(ref_chars) and j < len(hyp_chars):
                        errors.append(("替換", ref_chars[i], hyp_chars[j]))
            elif chunk.type == "delete":
                for i in range(chunk.ref_start_idx, chunk.ref_end_idx):
                    if i < len(ref_chars):
                        errors.append(("刪除", ref_chars[i], "—"))
            elif chunk.type == "insert":
                for j in range(chunk.hyp_start_idx, chunk.hyp_end_idx):
                    if j < len(hyp_chars):
                        errors.append(("插入", "—", hyp_chars[j]))
    except Exception:
        pass
    return errors[:max_examples * 3]  # 多取一些再統計


def count_errors(errors: list) -> dict:
    """統計各類型錯誤的頻率。"""
    from collections import Counter
    sub = Counter()
    dele = Counter()
    ins = Counter()
    for etype, ref_c, hyp_c in errors:
        if etype == "替換":
            sub[(ref_c, hyp_c)] += 1
        elif etype == "刪除":
            dele[ref_c] += 1
        elif etype == "插入":
            ins[hyp_c] += 1
    return {"substitute": sub, "delete": dele, "insert": ins}


# ============================================================================
# 主程式
# ============================================================================

def evaluate(hyp_path: Path, ref_path: Path, output_path: Path = None):
    # ── 讀入文字 ────────────────────────────────────────────────────────────
    hyp_raw = hyp_path.read_text(encoding="utf-8")
    ref_raw = ref_path.read_text(encoding="utf-8")

    # ── 前處理 ──────────────────────────────────────────────────────────────
    hyp_stripped = strip_timestamps(hyp_raw)
    ref_stripped  = ref_raw.strip()   # 官方文稿通常不含時間戳記

    hyp_norm = normalize(hyp_stripped)
    ref_norm  = normalize(ref_stripped)

    hyp_chars = list(hyp_norm)
    ref_chars  = list(ref_norm)

    # ── CER 計算 ─────────────────────────────────────────────────────────────
    cer = jiwer.cer(
        text_to_chars(ref_norm),
        text_to_chars(hyp_norm),
    )
    accuracy = max(0.0, 1.0 - cer)

    # ── 詳細 CER 分析 ─────────────────────────────────────────────────────
    out = jiwer.process_characters(
        text_to_chars(ref_norm),
        text_to_chars(hyp_norm),
    )
    n_ref  = out.references[0].count(" ") + 1 if ref_norm else 0
    n_sub  = out.substitutions
    n_del  = out.deletions
    n_ins  = out.insertions
    n_hits = out.hits

    # ── 錯誤列舉 ────────────────────────────────────────────────────────────
    errors = find_error_examples(ref_chars, hyp_chars, max_examples=30)
    err_counts = count_errors(errors)

    # ── 報告輸出 ─────────────────────────────────────────────────────────────
    lines = []
    lines.append("=" * 60)
    lines.append("  即時語音辨識 CER 評測報告")
    lines.append("=" * 60)
    lines.append(f"  辨識結果：{hyp_path.name}")
    lines.append(f"  官方文稿：{ref_path.name}")
    lines.append("")
    lines.append(f"  參考文稿總字數 (N) ：{n_ref:>6} 字")
    lines.append(f"  正確辨識   (Hits)  ：{n_hits:>6} 字")
    lines.append(f"  替換錯誤   (Sub)   ：{n_sub:>6} 字")
    lines.append(f"  刪除錯誤   (Del)   ：{n_del:>6} 字")
    lines.append(f"  插入錯誤   (Ins)   ：{n_ins:>6} 字")
    lines.append("")
    lines.append(f"  ┌─────────────────────────────────────┐")
    lines.append(f"  │  CER（字元錯誤率）：{cer:>7.2%}          │")
    lines.append(f"  │  準確率（1-CER） ：{accuracy:>7.2%}          │")
    lines.append(f"  └─────────────────────────────────────┘")
    lines.append("")

    # 錯誤占比分析
    if n_ref > 0:
        lines.append("── 錯誤來源分析 ──────────────────────────────────────")
        lines.append(f"  替換佔總錯誤：{n_sub/(n_sub+n_del+n_ins)*100:.1f}%  "
                     f"（最常見：辨識出近音字）")
        lines.append(f"  刪除佔總錯誤：{n_del/(n_sub+n_del+n_ins)*100:.1f}%  "
                     f"（最常見：背景雜訊過濾掉語音）")
        lines.append(f"  插入佔總錯誤：{n_ins/(n_sub+n_del+n_ins)*100:.1f}%  "
                     f"（最常見：靜音被誤辨識為文字）")
        lines.append("")

    # 最高頻替換錯誤
    if err_counts["substitute"]:
        lines.append("── Top 替換錯誤（參考字 → 辨識字）──────────────────")
        for (ref_c, hyp_c), cnt in err_counts["substitute"].most_common(15):
            lines.append(f"  「{ref_c}」→「{hyp_c}」  ×{cnt}")
        lines.append("")

    # 最高頻刪除錯誤
    if err_counts["delete"]:
        lines.append("── Top 刪除錯誤（哪些字被漏掉）─────────────────────")
        for ref_c, cnt in err_counts["delete"].most_common(10):
            lines.append(f"  「{ref_c}」被漏掉  ×{cnt}")
        lines.append("")

    # CER 評級
    lines.append("── 評級說明 ──────────────────────────────────────────")
    if accuracy >= 0.95:
        grade = "⭐⭐⭐⭐⭐ 優秀（可直接使用）"
    elif accuracy >= 0.90:
        grade = "⭐⭐⭐⭐   良好（少量人工校對）"
    elif accuracy >= 0.80:
        grade = "⭐⭐⭐     尚可（需校對，可輔助使用）"
    elif accuracy >= 0.70:
        grade = "⭐⭐       待改善（建議優化後再使用）"
    else:
        grade = "⭐         需重大優化"
    lines.append(f"  {grade}")
    lines.append("")
    lines.append("── 優化建議（依錯誤比例優先排序）────────────────────")
    lines.append("  1. 替換錯誤多 → 新增自訂詞彙表（vocabulary/）")
    lines.append("  2. 刪除錯誤多 → 降低 RMS 靜音門檻，或加大 chunk 秒數")
    lines.append("  3. 插入錯誤多 → 提高 RMS 靜音門檻，過濾背景雜訊")
    lines.append("  4. 整體差     → 考慮換模型（Gemini 2.5 > chirp_3）")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    if output_path:
        output_path.write_text(report, encoding="utf-8")
        print(f"\n報告已儲存至：{output_path}")

    return {"cer": cer, "accuracy": accuracy,
            "sub": n_sub, "del": n_del, "ins": n_ins, "n_ref": n_ref}


# ============================================================================
# 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="即時辨識 CER 評測工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--hyp", required=True, type=Path,
                        help="辨識結果 .txt（含時間戳記格式 [HH:MM:SS]）")
    parser.add_argument("--ref", required=True, type=Path,
                        help="官方文稿 .txt（純文字）")
    parser.add_argument("--output", type=Path, default=None,
                        help="報告輸出路徑（可選）")
    args = parser.parse_args()

    if not args.hyp.exists():
        print(f"[錯誤] 找不到辨識結果：{args.hyp}")
        sys.exit(1)
    if not args.ref.exists():
        print(f"[錯誤] 找不到官方文稿：{args.ref}")
        sys.exit(1)

    evaluate(args.hyp, args.ref, args.output)


if __name__ == "__main__":
    main()
