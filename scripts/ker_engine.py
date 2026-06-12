#!/usr/bin/env python3
"""
KER 關鍵詞錯誤率引擎 (Keyword Error Rate)
==========================================
版本: 1.0.0 (2026-06-12) — 北屯機廠根因調查任務 5

CER 把所有字元平等看待——「機廠→機場」只佔 0.1pp CER，但事故地點全錯。
KER 單獨追蹤關鍵詞的辨識成功率，補上 CER 看不見的語意風險。

指標定義（v1 計數法）：
    recall(k)  = min(ref 出現次數, hyp 出現次數) / ref 出現次數
    KER        = 1 − Σ hit / Σ ref 出現次數（以出現次數加權）
    幻覺(k)    = ref 無此詞、hyp 卻出現的次數

已知限制（v1 接受，文件化）：
  - 計數法不驗證出現位置，關鍵詞在錯誤位置「騙到分」理論上可能但極罕見；
    若實際出現誤判再升級為對齊法（cer_engine DP 回溯定位）。
  - 子字串關鍵詞（停準 ⊂ 未停準、三軌 ⊂ 三軌復電）計數互相重疊，
    偏差在 ref/hyp 兩側對稱、大致抵銷；逐詞明細仍可分辨。

關鍵詞來源：master_vocabulary.csv 的 alert_level ≥ 2 詞條（單一事實源，
加詞改 CSV 即可），與 cer_engine.normalize_text 同一套正規化。

用法：
    from scripts.ker_engine import load_keywords, calculate_ker

    kws = load_keywords()                  # 預設 alert_level >= 2
    result = calculate_ker(ref, hyp, kws)
    # result["ker"], result["recall"], result["hallucinations"],
    # result["by_keyword"][term] = {"ref": n, "hyp": n, "hit": n, ...}
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional

import sys

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from cer_engine import normalize_text  # noqa: E402

PROJECT_ROOT = _SCRIPTS_DIR.parent
DEFAULT_VOCAB_CSV = PROJECT_ROOT / "vocabulary" / "master_vocabulary.csv"


def load_keywords(
    csv_path: Optional[Path] = None,
    min_alert_level: int = 2,
) -> List[Dict]:
    """從 master_vocabulary.csv 載入關鍵詞（alert_level >= min_alert_level，去重）。

    回傳 [{"term": 原詞, "norm": 正規化詞, "alert_level": int, "category": str}, ...]
    """
    path = Path(csv_path) if csv_path else DEFAULT_VOCAB_CSV
    seen: set = set()
    keywords: List[Dict] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            term = (row.get("term") or "").strip()
            if not term or term.startswith("#"):
                continue
            level_raw = (row.get("alert_level") or "").strip()
            if not level_raw.isdigit() or int(level_raw) < min_alert_level:
                continue
            norm = normalize_text(term)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            keywords.append({
                "term": term,
                "norm": norm,
                "alert_level": int(level_raw),
                "category": (row.get("category") or "").strip(),
            })
    return keywords


def calculate_ker(reference: str, hypothesis: str, keywords: List[Dict]) -> Dict:
    """計算關鍵詞錯誤率。

    回傳 dict：
      ker            : float 0.0~1.0（ref 無任何關鍵詞時為 0.0）
      recall         : float 0.0~1.0（= 1 - ker）
      n_ref          : int  ref 中關鍵詞總出現次數
      n_hit          : int  命中次數（逐詞 min(ref, hyp) 加總）
      hallucinations : int  ref 無此詞、hyp 卻出現的總次數
      by_keyword     : dict term -> {ref, hyp, hit, alert_level, category}
                       （僅含 ref 或 hyp 至少出現一次的詞）
    """
    ref_norm = normalize_text(reference or "")
    hyp_norm = normalize_text(hypothesis or "")

    n_ref = n_hit = hallucinations = 0
    by_keyword: Dict[str, Dict] = {}

    for kw in keywords:
        norm = kw["norm"]
        rc = ref_norm.count(norm)
        hc = hyp_norm.count(norm)
        if rc == 0 and hc == 0:
            continue
        hit = min(rc, hc)
        n_ref += rc
        n_hit += hit
        if rc == 0:
            hallucinations += hc
        by_keyword[kw["term"]] = {
            "ref": rc,
            "hyp": hc,
            "hit": hit,
            "alert_level": kw["alert_level"],
            "category": kw["category"],
        }

    recall = (n_hit / n_ref) if n_ref else 1.0
    return {
        "ker": round(1.0 - recall, 6),
        "recall": round(recall, 6),
        "n_ref": n_ref,
        "n_hit": n_hit,
        "hallucinations": hallucinations,
        "by_keyword": by_keyword,
    }
