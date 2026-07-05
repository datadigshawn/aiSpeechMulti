#!/usr/bin/env python3
"""
Regression guard 指標（A4）
===========================
評測防守指標：平均 CER 之外，追蹤三類高語意風險目標的 recall，
防止「平均降但關鍵詞崩」的假改善（6-12 北屯 RCA 教訓）。

三個指標：
    1. 關鍵詞 recall — master_vocabulary alert_level ≥ 2（ker_engine 現成）
    2. 站碼 recall   — master_vocabulary category == station_code
    3. 車廂號 recall — regex 抽 token（數字串＋車/車門/動車），格式歸一後 multiset 計數

計數法同 ker_engine v1（min(ref, hyp) 命中、不驗證位置），已知限制見 ker_engine docstring。
車廂號格式歸一：中文/軍事數字→阿拉伯、去斜線與空白（07/08車 ≡ 0708 車 ≡ 洞拐洞八車）。

用法：
    from scripts.regression_guard import guard_metrics, aggregate_guard

    g = guard_metrics(gt_text, final_text)   # 逐段
    agg = aggregate_guard([g1, g2, ...])     # occurrence-weighted 彙總
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in (str(PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ker_engine import calculate_ker, load_keywords  # noqa: E402
from post_process import CHINESE_DIGITS  # noqa: E402

# 詞表載一次 cache
_KW_CACHE: dict = {}


def _keywords(kind: str) -> list[dict]:
    if kind in _KW_CACHE:
        return _KW_CACHE[kind]
    if kind == "kw":
        kws = load_keywords(min_alert_level=2)
    elif kind == "station":
        kws = [k for k in load_keywords(min_alert_level=0)
               if k["category"] == "station_code"]
    else:
        raise ValueError(kind)
    _KW_CACHE[kind] = kws
    return kws


# 車廂號兩種語序：數字在前（23/24車、0708車門）與車組在前（車組21/22）
_CAR_DIGIT = "[0-9" + "".join(CHINESE_DIGITS.keys()) + "]"
_CAR_NUM_SEQ = rf"(?:{_CAR_DIGIT}\s*[/／]?\s*){{2,4}}"
_CAR_SUFFIX_RE = re.compile(
    rf"({_CAR_NUM_SEQ})(動車門|動車|車門|車(?![組站輛廂掌]))"
)
_CAR_PREFIX_RE = re.compile(rf"(車組)\s*({_CAR_NUM_SEQ})")


def _norm_car_digits(raw: str) -> str:
    digits = "".join(CHINESE_DIGITS.get(c, c) for c in raw if not c.isspace())
    return digits.replace("/", "").replace("／", "")


def car_number_tokens(text: str) -> Counter:
    """抽車廂號 token：(歸一數字串, 語境詞)。格式差異（斜線/空白/中文數字）不影響比對。"""
    if not text:
        return Counter()
    tokens: Counter = Counter()
    for m in _CAR_SUFFIX_RE.finditer(text):
        digits = _norm_car_digits(m.group(1))
        if digits.isdigit():
            tokens[(digits, m.group(2))] += 1
    for m in _CAR_PREFIX_RE.finditer(text):
        digits = _norm_car_digits(m.group(2))
        if digits.isdigit():
            tokens[(digits, "車組")] += 1
    return tokens


def guard_metrics(reference: str, hypothesis: str) -> dict:
    """逐段三指標。回傳 {kw|station|car: {ref, hit, halluc}}。"""
    out: dict = {}
    for kind in ("kw", "station"):
        r = calculate_ker(reference, hypothesis, _keywords(kind))
        out[kind] = {"ref": r["n_ref"], "hit": r["n_hit"],
                     "halluc": r["hallucinations"]}
    ref_toks = car_number_tokens(reference)
    hyp_toks = car_number_tokens(hypothesis)
    hit = sum(min(c, hyp_toks[t]) for t, c in ref_toks.items())
    halluc = sum(c for t, c in hyp_toks.items() if t not in ref_toks)
    out["car"] = {"ref": sum(ref_toks.values()), "hit": hit, "halluc": halluc}
    return out


def aggregate_guard(metrics: list[dict]) -> dict:
    """occurrence-weighted 彙總：{kind: {ref, hit, halluc, recall}}。ref=0 時 recall=None。"""
    agg: dict = {}
    for kind in ("kw", "station", "car"):
        ref = sum(m[kind]["ref"] for m in metrics)
        hit = sum(m[kind]["hit"] for m in metrics)
        halluc = sum(m[kind]["halluc"] for m in metrics)
        agg[kind] = {
            "ref": ref, "hit": hit, "halluc": halluc,
            "recall": round(hit / ref, 4) if ref else None,
        }
    return agg


GUARD_LABELS = {"kw": "關鍵詞", "station": "站碼", "car": "車廂號"}
