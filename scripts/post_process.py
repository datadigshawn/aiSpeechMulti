#!/usr/bin/env python3
"""
語音辨識後處理 Pipeline
=======================

整合三層後處理：
    1. 車廂編號正規化（regex，零成本）
    2. correction_dict 同音字/術語修正（字串替換）
    3. LLM 後修正層（Gemini，可選）

每層都可獨立開關。回傳結果包含每階段的修正紀錄，方便 UI 顯示與審核。

用法：
    from scripts.post_process import post_process

    final, report = post_process(
        text,
        enable_car_norm=True,
        enable_dict=True,
        enable_llm=False,
        llm_model="gemini-2.5-flash",
        llm_strictness="conservative",
    )

    # report 結構：
    # {
    #   "stages": [
    #     {"name": "car_norm",   "applied": True, "changes": [...]},
    #     {"name": "dict",       "applied": True, "changes": [...]},
    #     {"name": "llm",        "applied": False, "changes": [], "skipped_reason": "disabled"},
    #   ],
    #   "total_changes": 7,
    #   "elapsed_sec": 0.12,
    # }
"""

from __future__ import annotations

import os
import json
import re
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 內部模組：車廂編號正規化 ─────────────────────────────────────────
# 原本位於 experiments/llm_correction_poc/car_number_normalizer.py
# 為了讓 production 程式能 import，這裡直接內嵌核心邏輯
# （也可以後續搬到 scripts/car_number_normalizer.py 共用）
CHINESE_DIGITS = {
    "零": "0", "〇": "0",
    "一": "1", "壹": "1",
    "二": "2", "兩": "2", "貳": "2",
    "三": "3", "參": "3", "叁": "3",
    "四": "4", "肆": "4",
    "五": "5", "伍": "5",
    "六": "6", "陸": "6",
    "七": "7", "柒": "7",
    "八": "8", "捌": "8",
    "九": "9", "玖": "9",
    "洞": "0",
    "么": "1", "腰": "1",
    "拐": "7",
    "勾": "9",
}
_CHN_DIGIT_CLASS = "[" + "".join(CHINESE_DIGITS.keys()) + "]"


def _chinese_to_arabic(s: str) -> str:
    return "".join(CHINESE_DIGITS.get(c, c) for c in s)


def normalize_car_numbers(text: str) -> tuple[str, list[dict]]:
    """車廂編號正規化（與 experiments 版本同步維護）"""
    if not text:
        return text, []
    changes: list[dict] = []
    result = text

    # Pass 1: 中文數字 → 阿拉伯
    chn_pattern = re.compile(
        rf"({_CHN_DIGIT_CLASS}{{2,4}})\s*(動車門|動車|車門|車(?![組站輛]))"
    )

    def chn_repl(m):
        chn_seq, suffix = m.group(1), m.group(2)
        arabic = _chinese_to_arabic(chn_seq)
        if not arabic.isdigit():
            return m.group(0)
        new = arabic + suffix
        changes.append({"from": m.group(0), "to": new, "rule": "chn_to_arabic"})
        return new

    result = chn_pattern.sub(chn_repl, result)

    # Pass 2: 4 位數字 → 拆對
    for suf in ("動車門", "動車", "車門"):
        pat = re.compile(rf"(?<![\d/])(\d{{2}})(\d{{2}})\s*{suf}")

        def split_repl(m, _s=suf):
            new = f"{m.group(1)}/{m.group(2)} {_s}"
            changes.append({"from": m.group(0), "to": new, "rule": f"split_4digit_{_s}"})
            return new

        result = pat.sub(split_repl, result)

    pat_car = re.compile(r"(?<![\d/])(\d{2})(\d{2})\s*車(?![組站輛門掌廂])")

    def split_car_repl(m):
        new = f"{m.group(1)}/{m.group(2)} 車"
        changes.append({"from": m.group(0), "to": new, "rule": "split_4digit_車"})
        return new

    result = pat_car.sub(split_car_repl, result)

    # Pass 3: X/Y 補零標準化
    slash_pat = re.compile(r"(\d{1,2})\s*[/／]\s*(\d{1,2})\s*(動車門|動車|車門|車(?![組站輛]))")

    def slash_repl(m):
        a, b, suf = m.group(1), m.group(2), m.group(3)
        new = f"{a.zfill(2)}/{b.zfill(2)} {suf}"
        if new != m.group(0):
            changes.append({"from": m.group(0), "to": new, "rule": "slash_normalize"})
        return new

    result = slash_pat.sub(slash_repl, result)

    # Pass 4: 1-2 位數字補空格
    for suf in ("動車門", "動車", "車門"):
        pat = re.compile(rf"(?<![\d/])(\d{{1,2}})\s*{suf}")

        def single_repl(m, _s=suf):
            new = f"{m.group(1)} {_s}"
            if new != m.group(0):
                changes.append({"from": m.group(0), "to": new, "rule": f"space_single_{_s}"})
            return new

        result = pat.sub(single_repl, result)

    pat_single_car = re.compile(r"(?<![\d/])(\d{1,2})\s*車(?![組站輛門掌廂])")

    def single_car_repl(m):
        new = f"{m.group(1)} 車"
        if new != m.group(0):
            changes.append({"from": m.group(0), "to": new, "rule": "space_single_車"})
        return new

    result = pat_single_car.sub(single_car_repl, result)

    result = re.sub(r"  +", " ", result)
    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 第二層：correction_dict（包裝既有 fix_radio_jargon）
# ══════════════════════════════════════════════════════════════════════
def apply_correction_dict(text: str) -> tuple[str, list[dict]]:
    """套用 vocabulary/correction_dict.py 的同音字/術語修正
    透過直接比對 RADIO_REPLACEMENT_RULES 取得 diff 資訊"""
    if not text:
        return text, []
    try:
        from vocabulary.correction_dict import RADIO_REPLACEMENT_RULES
    except ImportError:
        return text, []

    changes: list[dict] = []
    result = text
    for wrong, right in RADIO_REPLACEMENT_RULES.items():
        if wrong and right and wrong in result:
            count = result.count(wrong)
            result = result.replace(wrong, right)
            changes.append({"from": wrong, "to": right, "count": count, "rule": "correction_dict"})
    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 第三層：LLM 後修正（可選）
# ══════════════════════════════════════════════════════════════════════
LLM_SYSTEM_PROMPT = """你是台中捷運（TMRT）行控中心無線電通訊文字校正專家。

# 任務
修正語音辨識結果中的「字詞層級錯誤」（同音字、術語誤辨、簡繁混雜）。
你的角色是「校對員」，不是「編輯」。

# 修正強度: {strictness}
{strictness_rules}

# 絕對禁止
1. 禁止改寫 3 字以上連續詞組為意義不同的詞
2. 禁止新增、刪除、翻譯任何內容
3. 禁止語意推測（不確定就保留原文）
4. 禁止移除口語助詞（好、是、喔、那、吧）
5. 禁止改變講者標記內容

# 必須做
1. 簡體字 → 繁體字（台灣用法）
2. 已知術語誤辨修正：越台門→月台門、歐西/哦西→OCC、輔電/鋪電→復電、待行軌→待避軌
3. 通訊用語：喔飛→over
4. 軍事數字保留：洞=0、么/腰=1、兩=2、拐=7、勾=9

# 輸出（嚴格 JSON，無 markdown）
{{
  "corrected": "修正後全文",
  "changes": [{{"from": "...", "to": "...", "type": "term|s2t|homophone|comm"}}],
  "confidence": 0.95
}}
"""

_STRICTNESS_RULES = {
    "strict":       "- 只改術語對照表中明確列出的錯誤\n- 禁止任何語意推測",
    "conservative": "- 修正術語 + 簡繁 + 高信心同音字\n- 禁止 3 字以上詞組改寫",
    "balanced":     "- 修正術語 + 簡繁 + 同音字 + 標點補全",
}


def apply_llm_correction(
    text: str,
    model: str = "gemini-2.5-flash",
    strictness: str = "conservative",
    api_key: Optional[str] = None,
    timeout: int = 60,
) -> tuple[str, list[dict], Optional[str]]:
    """LLM 後修正。回傳: (修正後文字, changes, error_msg or None)"""
    if not text or not text.strip():
        return text, [], None

    try:
        from utils.gemini_client import get_client, genai_types
    except ImportError:
        return text, [], "未安裝 google-genai 或 utils.gemini_client 不可用"

    try:
        client = get_client(api_key)
    except ValueError as e:
        return text, [], str(e)

    try:
        sys_prompt = LLM_SYSTEM_PROMPT.format(
            strictness=strictness,
            strictness_rules=_STRICTNESS_RULES.get(strictness, _STRICTNESS_RULES["conservative"]),
        )
        resp = client.models.generate_content(
            model=model,
            contents=f"請修正以下無線電辨識結果：\n\n{text}\n\n輸出 JSON。",
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                system_instruction=sys_prompt,
            ),
        )
        raw = (resp.text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        data = json.loads(raw)
        corrected = data.get("corrected", text)
        changes = data.get("changes", [])
        return corrected, changes, None
    except Exception as e:
        return text, [], f"LLM 呼叫失敗: {type(e).__name__}: {str(e)[:200]}"


def _resolve_api_key() -> Optional[str]:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    json_path = PROJECT_ROOT / "utils" / "api_keys.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for k in ("gemini_api_key", "GEMINI_API_KEY", "google_api_key"):
                if data.get(k):
                    return data[k]
        except Exception:
            pass
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ══════════════════════════════════════════════════════════════════════
# CER-aware rollback（#9）：用 4-gram LM 偵測 LLM 過度修正
# ══════════════════════════════════════════════════════════════════════
# 載一次後 cache，不每次 post_process 都 unpickle
_NGRAM_LM_CACHE: dict = {"loaded": False, "lm": None, "available": False}


class _LMUnpickler:
    """Custom Unpickler 解決 pickle 存的 class 路徑為 '__main__' 的問題
    （build_ngram_lm.py 用 CLI 訓練時 class 屬於 __main__）"""

    def __init__(self, file):
        import pickle as _pickle
        # 動態建一個子類覆寫 find_class
        class _Wrapper(_pickle.Unpickler):
            def find_class(self, module, name):
                if name == "CharNgramLM":
                    from scripts.build_ngram_lm import CharNgramLM
                    return CharNgramLM
                return super().find_class(module, name)
        self._inner = _Wrapper(file)

    def load(self):
        return self._inner.load()


def _get_ngram_lm():
    """惰性載入 4-gram LM（experiments/ngram_lm/char_4gram.pkl）"""
    if _NGRAM_LM_CACHE["loaded"]:
        return _NGRAM_LM_CACHE["lm"]
    _NGRAM_LM_CACHE["loaded"] = True
    try:
        from pathlib import Path as _Path
        lm_path = _Path(__file__).resolve().parent.parent / "experiments" / "ngram_lm" / "char_4gram.pkl"
        if not lm_path.exists():
            _NGRAM_LM_CACHE["available"] = False
            return None
        with open(lm_path, "rb") as f:
            lm = _LMUnpickler(f).load()
        _NGRAM_LM_CACHE["lm"] = lm
        _NGRAM_LM_CACHE["available"] = True
        return lm
    except Exception as e:
        _NGRAM_LM_CACHE["available"] = False
        _NGRAM_LM_CACHE["error"] = str(e)
        return None


def _check_perplexity_rollback(
    pre: str,
    post: str,
    threshold_ratio: float = 2.0,
) -> tuple[bool, dict]:
    """
    依 4-gram LM 判斷 LLM 後修正是否「過度修改」需要 rollback。

    Args:
        pre: LLM 修正前文字
        post: LLM 修正後文字
        threshold_ratio: post_pp / pre_pp 比例超過此值就 rollback（預設 2.0 = 變兩倍）

    Returns:
        (should_rollback: bool, info: dict)
        info 含 pre_pp / post_pp / ratio / available
    """
    lm = _get_ngram_lm()
    info = {"available": lm is not None, "threshold_ratio": threshold_ratio}
    if lm is None or not pre or not post or pre == post:
        info.update({"pre_pp": None, "post_pp": None, "ratio": None})
        return False, info

    try:
        pre_pp = lm.perplexity(pre)
        post_pp = lm.perplexity(post)
        info["pre_pp"] = round(pre_pp, 2)
        info["post_pp"] = round(post_pp, 2)
        # 處理極端值（無限大時直接視為 rollback）
        import math as _math
        if _math.isinf(post_pp) and not _math.isinf(pre_pp):
            info["ratio"] = float("inf")
            return True, info
        if pre_pp <= 0:
            info["ratio"] = None
            return False, info
        ratio = post_pp / pre_pp
        info["ratio"] = round(ratio, 3)
        return ratio > threshold_ratio, info
    except Exception as e:
        info["error"] = str(e)[:200]
        return False, info


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
# ── 高品質引擎清單（LLM smart skip 用）──────────────────────────────
# 這些引擎本身已是 LLM 等級或自帶語意理解，再用 LLM 後修正
# 多半「過度修改」反而降低 CER，依 A/B 測試結果動態調整。
HIGH_QUALITY_ENGINES = {"gemini", "hybrid"}


def post_process(
    text: str,
    enable_car_norm: bool = True,
    enable_dict: bool = True,
    enable_llm: bool = False,
    enable_cer_rollback: bool = True,
    cer_rollback_threshold: float = 2.0,
    llm_model: str = "gemini-2.5-flash",
    llm_strictness: str = "conservative",
    engine_hint: Optional[str] = None,
    auto_skip_llm_for_high_quality: bool = False,
    enable_term_filter: bool = True,
    enable_number_norm: bool = True,
    enable_contextual: bool = True,
) -> tuple[str, dict]:
    """執行後處理 pipeline

    Pipeline 順序：
        [term_filter.blacklist] → car_norm → dict →
            [term_filter.protect] → llm → [term_filter.restore]

    Args:
        text: 原始 STT 辨識文字
        enable_car_norm: 是否啟用車廂編號正規化
        enable_dict: 是否啟用 correction_dict 字串替換
        enable_llm: 是否啟用 LLM 後修正
        llm_model: LLM 模型名稱
        llm_strictness: LLM 修正強度（strict/conservative/balanced）
        engine_hint: 上游 STT 引擎類型，用於 LLM smart skip 判斷
        auto_skip_llm_for_high_quality: True 時若 engine_hint 屬於 HIGH_QUALITY_ENGINES
                     會自動跳過 LLM 階段
        enable_term_filter: 是否啟用術語黑白名單（預設開）
                     - Blacklist 會在最早階段強制替換絕對錯字
                     - Whitelist 會在 LLM 階段用 placeholder 保護關鍵術語

    Returns:
        (final_text, report_dict)
    """
    t0 = time.time()
    stages = []
    current = text or ""
    original = current
    # snapshots：紀錄 pipeline 關鍵節點的版本，供 #17 版本管理 / dashboard 對照
    snapshots: dict[str, str] = {"raw": original}

    # Stage 0: Term filter blacklist（強制替換絕對錯字）
    if enable_term_filter:
        try:
            from scripts.term_filter import TermFilter
            _tf = TermFilter(engine_hint=engine_hint)
            current, tf_changes = _tf.apply_blacklist_with_log(current)
            stages.append({
                "name": "term_blacklist",
                "applied": True,
                "changes": [
                    {"from": c.original, "to": c.replaced, "count": c.count,
                     "rule": "blacklist"}
                    for c in tf_changes
                ],
                "change_count": len(tf_changes),
            })
        except Exception as _tfe:
            stages.append({
                "name": "term_blacklist",
                "applied": False,
                "changes": [],
                "change_count": 0,
                "error": f"TermFilter 失敗: {_tfe}",
            })
    else:
        stages.append({"name": "term_blacklist", "applied": False,
                       "changes": [], "change_count": 0})

    # Stage 1: 車廂編號正規化
    if enable_car_norm:
        current, car_changes = normalize_car_numbers(current)
        stages.append({
            "name": "car_norm",
            "applied": True,
            "changes": car_changes,
            "change_count": len(car_changes),
        })
    else:
        stages.append({"name": "car_norm", "applied": False, "changes": [], "change_count": 0})

    # Stage 1.5: 數字/時間/站碼正規化
    if enable_number_norm:
        try:
            from scripts.number_normalizer import normalize_numbers
            current, num_changes = normalize_numbers(current)
            stages.append({
                "name": "number_norm",
                "applied": True,
                "changes": num_changes,
                "change_count": len(num_changes),
            })
        except Exception as _nne:
            stages.append({
                "name": "number_norm",
                "applied": False,
                "changes": [],
                "change_count": 0,
                "error": f"NumberNormalizer 失敗: {_nne}",
            })
    else:
        stages.append({"name": "number_norm", "applied": False,
                       "changes": [], "change_count": 0})

    # snapshot：到此為止「車號 + 數字正規化」結束
    snapshots["after_car_norm"] = current

    # Stage 2: correction_dict
    if enable_dict:
        current, dict_changes = apply_correction_dict(current)
        stages.append({
            "name": "dict",
            "applied": True,
            "changes": dict_changes,
            "change_count": len(dict_changes),
        })
    else:
        stages.append({"name": "dict", "applied": False, "changes": [], "change_count": 0})

    # Stage 2.5: contextual corrections（上下文敏感三元組）
    if enable_contextual:
        try:
            from scripts.contextual_corrector import ContextualCorrector
            _cc = ContextualCorrector(engine_hint=engine_hint)
            current, ctx_changes = _cc.apply(current)
            stages.append({
                "name": "contextual",
                "applied": True,
                "changes": ctx_changes,
                "change_count": len(ctx_changes),
            })
        except Exception as _cce:
            stages.append({
                "name": "contextual",
                "applied": False,
                "changes": [],
                "change_count": 0,
                "error": f"ContextualCorrector 失敗: {_cce}",
            })
    else:
        stages.append({"name": "contextual", "applied": False,
                       "changes": [], "change_count": 0})

    # snapshot：到此為止「dict + contextual」結束
    snapshots["after_dict"] = current

    # Stage 3: LLM（含 smart skip + whitelist 保護）
    if enable_llm:
        # Smart skip: 若上游已是高品質 LLM-grade 引擎，跳過 LLM 後修正
        # 因為實測顯示 Gemini 等引擎被 LLM 修正後反而 CER 變糟
        if (
            auto_skip_llm_for_high_quality
            and engine_hint
            and engine_hint.lower() in HIGH_QUALITY_ENGINES
        ):
            stages.append({
                "name": "llm",
                "applied": False,
                "changes": [],
                "change_count": 0,
                "skipped_reason": (
                    f"smart_skip: 上游引擎 '{engine_hint}' 為高品質 LLM-grade，"
                    f"再次套用 LLM 後修正可能造成過度修改（依 A/B 測試結果）"
                ),
            })
        else:
            # Whitelist 保護：把關鍵術語換成 placeholder，避免 LLM 誤改
            _placeholder_map: dict = {}
            if enable_term_filter:
                try:
                    from scripts.term_filter import TermFilter
                    _tf = TermFilter(engine_hint=engine_hint)
                    current, _placeholder_map = _tf.protect_whitelist(current)
                except Exception:
                    _placeholder_map = {}

            corrected, llm_changes, err = apply_llm_correction(
                current, model=llm_model, strictness=llm_strictness
            )
            stage = {
                "name": "llm",
                "applied": True,
                "changes": llm_changes,
                "change_count": len(llm_changes),
                "model": llm_model,
                "strictness": llm_strictness,
            }
            if err:
                stage["error"] = err

            # 還原 whitelist placeholder
            if _placeholder_map:
                from scripts.term_filter import TermFilter
                _tf = TermFilter(engine_hint=engine_hint)
                corrected = _tf.restore_whitelist(corrected, _placeholder_map)
                current = _tf.restore_whitelist(current, _placeholder_map)
                stage["whitelist_protected"] = len(_placeholder_map)

            # CER-aware rollback (#9)：用 4-gram LM 判斷 LLM 是否過度修正
            # 若修正後 perplexity / 修正前 perplexity > threshold（預設 2x）→ 回退
            if enable_cer_rollback and not err and corrected != current:
                should_rollback, rb_info = _check_perplexity_rollback(
                    pre=current, post=corrected,
                    threshold_ratio=cer_rollback_threshold,
                )
                stage["rollback_check"] = rb_info
                if should_rollback:
                    stage["rolled_back"] = True
                    stage["change_count"] = 0
                    stage["changes"] = []
                    # 不改 current，保留 LLM 修正前的版本
                else:
                    current = corrected
            else:
                current = corrected
            stages.append(stage)
    else:
        stages.append({"name": "llm", "applied": False, "changes": [], "change_count": 0})

    # snapshot：pipeline 終點（含 LLM 階段）
    snapshots["after_llm"] = current

    report = {
        "stages": stages,
        "total_changes": sum(s["change_count"] for s in stages),
        "elapsed_sec": round(time.time() - t0, 3),
        "original_length": len(original),
        "final_length": len(current),
        # 各階段 snapshot：keys = raw / after_car_norm / after_dict / after_llm
        # 供 #17 版本管理 + dashboard 對照
        "snapshots": snapshots,
    }
    return current, report


# ══════════════════════════════════════════════════════════════════════
# CLI 測試
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--text", help="輸入文字")
    p.add_argument("--file", help="輸入檔案")
    p.add_argument("--no-car", action="store_true")
    p.add_argument("--no-dict", action="store_true")
    p.add_argument("--llm", action="store_true", help="啟用 LLM 修正")
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--strictness", default="conservative")
    args = p.parse_args()

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        print("需要 --text 或 --file")
        exit(1)

    final, report = post_process(
        text,
        enable_car_norm=not args.no_car,
        enable_dict=not args.no_dict,
        enable_llm=args.llm,
        llm_model=args.model,
        llm_strictness=args.strictness,
    )

    print("─── 原文 ───")
    print(text)
    print("\n─── 修正後 ───")
    print(final)
    print(f"\n─── 報告 ───")
    print(f"總修正: {report['total_changes']} 處 / 耗時 {report['elapsed_sec']}s")
    for s in report["stages"]:
        flag = "✅" if s["applied"] else "⏭️"
        print(f"  {flag} {s['name']:10} ({s['change_count']} 處)")
        if s.get("error"):
            print(f"     ❌ {s['error']}")
        for c in s["changes"][:5]:
            print(f"     · {c.get('from')!r} → {c.get('to')!r}")
        if len(s["changes"]) > 5:
            print(f"     ... 還有 {len(s['changes'])-5} 處")
