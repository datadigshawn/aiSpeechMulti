#!/usr/bin/env python3
"""
Phase 5 B3：領域 4-gram 字級語言模型
========================================

從 GT + DB 累積的人工修正建一個簡易的 4-gram 字級 LM，用來：
1. 評估 STT 輸出的 perplexity（流暢度）
2. 後續可整合進 post_process 做「LLM 改太多 → rollback」判斷
3. 為 Phase 5 fine-tune 提供領域語言模型 baseline

實作：純 Python + Stupid Backoff（α=0.4），不需 kenlm 編譯
- 小資料集（< 10k tokens）夠用
- API 與 kenlm 相容（log10 score）
- 輸出 .pkl 模型 + perplexity 報告

用法：
    # 訓練（從 GT + DB corrections）
    python3 scripts/build_ngram_lm.py --train

    # 評估某段 perplexity
    python3 scripts/build_ngram_lm.py --score "OCC呼叫G05四維站長"

    # 評估 STT 輸出的 perplexity 分布
    python3 scripts/build_ngram_lm.py --eval-stt gemini25pro
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "ground_truth"
MANIFEST_PATH = PROJECT_ROOT / "experiments" / "golden_dataset" / "manifest.csv"
DB_PATH = PROJECT_ROOT / "data" / "aiSpeechMulti.db"
STT_DIR = PROJECT_ROOT / "experiments" / "golden_dataset" / "stt_outputs"
LM_DIR = PROJECT_ROOT / "experiments" / "ngram_lm"


# ══════════════════════════════════════════════════════════════════════
# 文本清理（與 build_finetune_dataset 一致）
# ══════════════════════════════════════════════════════════════════════
def clean_for_lm(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"^[A-Z?]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"[\(（]沉默\s*[\d一二三四五六七八九十]+\s*秒?[\)）]", "", text)
    text = re.sub(r"[\(（](?:笑聲|咳嗽|雜音|noise|laughter|cough|unclear)[\)）]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


# ══════════════════════════════════════════════════════════════════════
# 4-gram LM with Stupid Backoff
# ══════════════════════════════════════════════════════════════════════
class CharNgramLM:
    """字級 N-gram 語言模型（純 Python + Stupid Backoff）"""

    def __init__(self, order: int = 4, alpha: float = 0.4):
        self.order = order      # n-gram 階數
        self.alpha = alpha      # Stupid Backoff 折扣係數
        # 各階 n-gram 計數
        # ngrams[n] = {tuple(chars): count}
        self.ngrams: dict[int, Counter] = {n: Counter() for n in range(1, order + 1)}
        # contexts[n] = {prefix_tuple: total_count}（給條件機率用）
        self.contexts: dict[int, Counter] = {n: Counter() for n in range(1, order + 1)}
        self.vocab_size = 0
        self.total_tokens = 0
        self.bos = "<s>"
        self.eos = "</s>"

    def train(self, sentences: list[str]) -> None:
        """sentences: list of cleaned text（每句已 clean_for_lm 處理過）"""
        vocab = set()
        for sent in sentences:
            chars = list(sent)
            if not chars:
                continue
            # 加 BOS/EOS（重複 order-1 次補齊 context）
            tokens = [self.bos] * (self.order - 1) + chars + [self.eos]
            self.total_tokens += len(chars)
            vocab.update(chars)

            # 計各階 n-gram 與 context
            for n in range(1, self.order + 1):
                for i in range(len(tokens) - n + 1):
                    ngram = tuple(tokens[i:i + n])
                    self.ngrams[n][ngram] += 1
                    if n > 1:
                        self.contexts[n][ngram[:-1]] += 1
                    else:
                        self.contexts[1][()] += 1

        self.vocab_size = len(vocab)

    def _conditional_prob(self, n: int, ngram: tuple) -> float:
        """條件機率 P(c | context) with Stupid Backoff"""
        if n == 1:
            # unigram: count / total
            count = self.ngrams[1].get(ngram, 0)
            total = self.contexts[1].get((), 1)
            if count == 0:
                # 對 vocab 外字元給極小機率（避免 log(0)）
                return 1.0 / max(self.total_tokens, 1) / 10
            return count / total

        count = self.ngrams[n].get(ngram, 0)
        ctx_count = self.contexts[n].get(ngram[:-1], 0)
        if count > 0 and ctx_count > 0:
            return count / ctx_count
        # backoff to (n-1)-gram with α discount
        return self.alpha * self._conditional_prob(n - 1, ngram[1:])

    def log10_prob(self, text: str) -> float:
        """log10 P(text)（KenLM 介面相容）"""
        chars = list(clean_for_lm(text))
        if not chars:
            return 0.0
        tokens = [self.bos] * (self.order - 1) + chars + [self.eos]
        log_prob = 0.0
        for i in range(self.order - 1, len(tokens)):
            ngram = tuple(tokens[i - self.order + 1:i + 1])
            p = self._conditional_prob(self.order, ngram)
            log_prob += math.log10(max(p, 1e-12))
        return log_prob

    def perplexity(self, text: str) -> float:
        """字元級 perplexity（越低越流暢）"""
        chars = list(clean_for_lm(text))
        if not chars:
            return float("inf")
        log_prob = self.log10_prob(text)
        # log10 → ln，perplexity = exp(-log_prob_per_token / n)
        # 使用 +1 包含 EOS
        N = len(chars) + 1
        return 10 ** (-log_prob / N)

    def stats(self) -> dict:
        return {
            "order":         self.order,
            "alpha":         self.alpha,
            "vocab_size":    self.vocab_size,
            "total_tokens":  self.total_tokens,
            **{f"ngram_{n}_unique": len(self.ngrams[n]) for n in range(1, self.order + 1)},
        }


# ══════════════════════════════════════════════════════════════════════
# 訓練資料載入
# ══════════════════════════════════════════════════════════════════════
def load_training_sentences() -> list[str]:
    """從 GT + DB 累積的 corrected 收集所有句子"""
    sents = []
    # 1. 黃金語料集 GT
    for gt_path in sorted(GT_DIR.glob("*.txt")):
        if gt_path.stem.startswith("000_example"):
            continue
        text = gt_path.read_text(encoding="utf-8")
        cleaned = clean_for_lm(text)
        if cleaned:
            sents.append(cleaned)
    # 2. DB 累積的人工修正
    if DB_PATH.exists():
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT corrected_transcript FROM transcriptions "
            "WHERE corrected_transcript IS NOT NULL"
        ).fetchall()
        conn.close()
        for (txt,) in rows:
            cleaned = clean_for_lm(txt or "")
            if cleaned:
                sents.append(cleaned)
    return sents


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
def cmd_train(args):
    sents = load_training_sentences()
    print(f"📋 訓練資料: {len(sents)} 句")
    print(f"   總字數: {sum(len(s) for s in sents)} 字")

    lm = CharNgramLM(order=args.order, alpha=args.alpha)
    lm.train(sents)
    stats = lm.stats()
    print()
    print(f"📊 LM 統計:")
    for k, v in stats.items():
        print(f"   {k}: {v}")

    LM_DIR.mkdir(parents=True, exist_ok=True)
    pkl_path = LM_DIR / f"char_{args.order}gram.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(lm, f)
    (LM_DIR / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"✅ 已儲存模型: {pkl_path}")

    # 對訓練集自身計算 perplexity（sanity check）
    train_pps = [lm.perplexity(s) for s in sents if s]
    train_pps = [p for p in train_pps if math.isfinite(p)]
    if train_pps:
        avg_pp = sum(train_pps) / len(train_pps)
        print(f"   訓練集平均 perplexity: {avg_pp:.2f}（越低越好）")


def cmd_score(args):
    pkl_path = LM_DIR / f"char_{args.order}gram.pkl"
    if not pkl_path.exists():
        print(f"❌ 模型不存在: {pkl_path}，請先 --train")
        return
    with open(pkl_path, "rb") as f:
        lm = pickle.load(f)
    pp = lm.perplexity(args.text)
    log_p = lm.log10_prob(args.text)
    print(f"text:        {args.text!r}")
    print(f"perplexity:  {pp:.2f}")
    print(f"log10 prob:  {log_p:.2f}")


def cmd_eval_stt(args):
    pkl_path = LM_DIR / f"char_{args.order}gram.pkl"
    if not pkl_path.exists():
        print(f"❌ 模型不存在: {pkl_path}，請先 --train")
        return
    with open(pkl_path, "rb") as f:
        lm = pickle.load(f)

    # 評估指定引擎所有段的 perplexity 分布
    eng_dir = STT_DIR / args.eval_stt
    if not eng_dir.exists():
        print(f"❌ {eng_dir} 不存在")
        return

    # 同時計算 GT 對照
    gt_map = {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("has_gt") == "Y":
                gt_map[r["id"]] = PROJECT_ROOT / r["gt_file"]

    print(f"🔬 perplexity 對照（{args.eval_stt} vs GT）")
    print(f"{'id':<5} {'event':<10} {'GT pp':>10} {'STT pp':>10} {'Δ pp':>10}")
    print("-" * 55)
    gt_pps, stt_pps = [], []
    for sid in sorted(gt_map.keys()):
        stt_path = eng_dir / f"{sid}.txt"
        if not stt_path.exists():
            continue
        gt_text = gt_map[sid].read_text(encoding="utf-8")
        stt_text = stt_path.read_text(encoding="utf-8")
        gt_pp = lm.perplexity(gt_text)
        stt_pp = lm.perplexity(stt_text)
        # 找 event_type
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            et = next((r["event_type"] for r in csv.DictReader(f) if r["id"] == sid), "?")
        if math.isfinite(gt_pp) and math.isfinite(stt_pp):
            gt_pps.append(gt_pp)
            stt_pps.append(stt_pp)
            delta = stt_pp - gt_pp
            print(f"{sid:<5} {et:<10} {gt_pp:>10.1f} {stt_pp:>10.1f} {delta:>+10.1f}")

    if gt_pps and stt_pps:
        print()
        print(f"平均 GT  perplexity: {sum(gt_pps)/len(gt_pps):8.2f}")
        print(f"平均 STT perplexity: {sum(stt_pps)/len(stt_pps):8.2f}")
        print(f"差距: {(sum(stt_pps)-sum(gt_pps))/len(gt_pps):+.2f}")
        print()
        print("解讀：STT pp >> GT pp 代表辨識結果語言模型機率低（不夠流暢），")
        print("      可作為「辨識品質代理指標」或 LLM 後修正 rollback 判斷。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=int, default=4, help="N-gram 階數（預設 4）")
    ap.add_argument("--alpha", type=float, default=0.4, help="Stupid Backoff 折扣（預設 0.4）")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--train", action="store_true", help="訓練 LM")
    grp.add_argument("--score", help="評估某段文字的 perplexity")
    grp.add_argument("--eval-stt", help="對指定 STT 引擎所有段做 perplexity 對照")
    args = ap.parse_args()

    if args.train:
        cmd_train(args)
    elif args.score:
        args.text = args.score
        cmd_score(args)
    elif args.eval_stt:
        cmd_eval_stt(args)


if __name__ == "__main__":
    main()
