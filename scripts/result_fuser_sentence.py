#!/usr/bin/env python3
"""
句子層級雙引擎融合器 (SentenceLevelFuser)
==========================================
版本: 2.0.0 (2026-04-08)

擴充自 scripts/result_fuser.py（原 ResultFuser 整段融合），改為逐句融合：

  音檔 ─┬─→ 引擎 A (例如 chirp_3)  ──→ 結果 A（句子清單）
        └─→ 引擎 B (例如 Gemini)    ──→ 結果 B（句子清單）
                                          │
                                          ▼
                         句子層級對齊（difflib 最長公共子序列）
                                          │
                                          ▼
                 逐句 CER 比對 + 特殊規則 + LLM 仲裁
                                          │
                                          ▼
                                    最佳融合結果

融合策略：
  1. 句子切分：用中文標點 + 換行 + 停頓詞切分兩組結果
  2. 句子對齊：用 difflib.SequenceMatcher 找出最佳對應關係
  3. 逐對決策（依優先順序）：
     R1. 含站碼/車廂/術語 → 優先取 Gemini（語意理解較強）
     R2. CER < 15%（高度一致）→ 取較完整的一方（字數較多）
     R3. 15% ≤ CER < 30%（中度差異）→ 取 Gemini
     R4. CER ≥ 30%（極大差異）→ LLM 仲裁（若啟用），否則取較長者
     R5. 只有一邊有句子 → 取該邊
  4. 融合：保留對齊後的順序，輸出完整段落

預期改善：
- 利用 chirp_3 對「通訊短句」的準度 + Gemini 對「長段落」的完整度
- 對 chirp3_v1（baseline CER 57.68%）預期可降至 35~40%

用法（模組）：
    from scripts.result_fuser_sentence import SentenceLevelFuser

    fuser = SentenceLevelFuser(llm_arbitration=True)
    result = fuser.fuse(
        text_a="chirp_3 辨識結果...",
        text_b="Gemini 辨識結果...",
        engine_a="chirp_3",
        engine_b="gemini",
    )
    print(result["transcript"])        # 融合後全文
    print(result["sentence_decisions"]) # 逐句決策紀錄

用法（CLI）：
    python3 scripts/result_fuser_sentence.py \\
        --text-a path/to/chirp3.txt \\
        --text-b path/to/gemini.txt \\
        --engine-a chirp_3 \\
        --engine-b gemini \\
        [--llm]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import jiwer
except ImportError:
    print("❌ 請先安裝: pip install jiwer")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# 常數定義
# ══════════════════════════════════════════════════════════════════════
# 高度一致門檻
_DEFAULT_HIGH_CONSISTENCY = 0.15
# 中度差異門檻
_DEFAULT_MEDIUM_DIFF = 0.30
# 最短句子長度（太短不計入）
_MIN_SENTENCE_LEN = 2

# 關鍵術語 regex（含這些的句子優先取 Gemini）
CRITICAL_TERMS_PATTERN = re.compile(
    r"[GgRr]\d{1,2}"                          # 站碼 G07/R01
    r"|\d{1,3}\s*/\s*\d{1,3}\s*車"             # 車廂 25/26 車
    r"|\d+\s*車(?![組站輛廂])"                 # 單節車廂
    r"|[一二三四五12345]\s*月台"               # 月台
    r"|\b(OCC|MTC|ATP|ATO|EDRH|MCP|CBTC|NCP|ETF|VVVF|ASR|MCS|RF|AM)\b"
    r"|復電|斷電|清車|停準|未停準|引導|登上|通告|回報|呼叫"
)


# ══════════════════════════════════════════════════════════════════════
# 資料結構
# ══════════════════════════════════════════════════════════════════════
@dataclass
class SentenceDecision:
    """逐句融合決策紀錄"""
    idx: int
    sentence_a: str
    sentence_b: str
    cer: Optional[float]
    decision: str           # "A" | "B" | "LLM" | "A_only" | "B_only" | "both_empty"
    rule: str               # "R1_critical" | "R2_similar" | "R3_medium" | "R4_llm" | "R4_fallback" | "R5_single"
    chosen_text: str
    has_critical: bool
    llm_raw: Optional[str] = None
    notes: str = ""


# ══════════════════════════════════════════════════════════════════════
# 句子切分（多層策略）
# ══════════════════════════════════════════════════════════════════════
# 第一層：句末標點
_SENTENCE_END_PATTERN = re.compile(r"[。！？\!\?]+")

# 第二層：通訊用語邊界（切在這些詞「之後」）
_COMM_BOUNDARY_WORDS = [
    r"\bover\b", r"\bOVER\b", r"\boveR\b",
    r"收到", r"完畢", r"稍後", r"回報",
    r"通告完畢", r"通話完畢",
]
_COMM_BOUNDARY_PATTERN = re.compile(
    r"(" + "|".join(_COMM_BOUNDARY_WORDS) + r")",
)

# 第三層：角色/事件起始（切在這些詞「之前」）
_ROLE_START_PATTERN = re.compile(
    r"(?=[GgRr]\d{1,2}\s*(?:呼叫|站長|回報|通告)"
    r"|OCC\s*(?:呼叫|通告|回報|回復)"
    r"|站長\s*(?:回報|呼叫))"
)

# 長句強制切分長度
_MAX_SENTENCE_LEN = 40


def split_sentences(text: str) -> list[str]:
    """將段落切成句子清單（多層策略）

    策略：
    1. 移除講者標記
    2. 用句末標點 + 換行初步切句
    3. 每句再用「通訊邊界詞」（over/收到/完畢）切
    4. 再用「角色起始詞」（G07 呼叫 / OCC 通告）切
    5. 超過 40 字的強制用空格切
    6. 過濾過短句
    """
    if not text:
        return []

    # 移除講者標記
    text = re.sub(r"【[^】]*】", "", text)
    # 正規化多空格為單空格
    text = re.sub(r"[ \t]+", " ", text)

    # ── 第一輪：換行 + 句末標點 ──────────────────────────────────
    level1: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 句末標點切
        parts = _SENTENCE_END_PATTERN.split(line)
        for p in parts:
            p = p.strip()
            if p:
                level1.append(p)

    # ── 第二輪：通訊邊界詞（切在詞之後）──────────────────────────
    level2: list[str] = []
    for s in level1:
        # 用 lookahead 保留邊界詞
        # 把 "xxx over yyy" 切成 ["xxx over", "yyy"]
        matches = list(_COMM_BOUNDARY_PATTERN.finditer(s))
        if not matches:
            level2.append(s)
            continue
        prev_end = 0
        for m in matches:
            end = m.end()
            chunk = s[prev_end:end].strip()
            if chunk:
                level2.append(chunk)
            prev_end = end
        # 剩餘尾巴
        tail = s[prev_end:].strip()
        if tail:
            level2.append(tail)

    # ── 第三輪：角色起始詞（切在詞之前）──────────────────────────
    level3: list[str] = []
    for s in level2:
        parts = _ROLE_START_PATTERN.split(s)
        for p in parts:
            p = p.strip()
            if p:
                level3.append(p)

    # ── 第四輪：超長句強制切分 ────────────────────────────────────
    level4: list[str] = []
    for s in level3:
        if len(s) <= _MAX_SENTENCE_LEN:
            level4.append(s)
            continue
        # 優先用空格切
        if " " in s:
            words = s.split(" ")
            chunk = []
            chunk_len = 0
            for w in words:
                if chunk_len + len(w) > _MAX_SENTENCE_LEN and chunk:
                    level4.append(" ".join(chunk))
                    chunk = [w]
                    chunk_len = len(w)
                else:
                    chunk.append(w)
                    chunk_len += len(w) + 1
            if chunk:
                level4.append(" ".join(chunk))
        else:
            # 沒空格 → 每 _MAX_SENTENCE_LEN 字硬切
            for i in range(0, len(s), _MAX_SENTENCE_LEN):
                level4.append(s[i:i + _MAX_SENTENCE_LEN])

    # ── 過濾過短句 ────────────────────────────────────────────────
    return [s for s in level4 if len(s) >= _MIN_SENTENCE_LEN]


# ══════════════════════════════════════════════════════════════════════
# 句子正規化（CER 比對用）
# ══════════════════════════════════════════════════════════════════════
def normalize_for_cer(text: str) -> str:
    """移除標點與空白，統一繁體"""
    if not text:
        return ""
    text = re.sub(r"[\s,，。.、:：;；!?！？\-—()（）\"'\u201c\u201d]+", "", text)
    try:
        from opencc import OpenCC
        text = OpenCC("s2twp").convert(text)
    except Exception:
        pass
    return text


def compute_sentence_cer(a: str, b: str) -> float:
    """計算兩句的 CER（已正規化）"""
    a_norm = normalize_for_cer(a)
    b_norm = normalize_for_cer(b)
    if not a_norm and not b_norm:
        return 0.0
    if not a_norm or not b_norm:
        return 1.0
    return jiwer.cer(a_norm, b_norm)


def has_critical_terms(text: str) -> bool:
    """偵測是否含站碼/車廂/術語"""
    if not text:
        return False
    return bool(CRITICAL_TERMS_PATTERN.search(text))


# ══════════════════════════════════════════════════════════════════════
# 句子對齊（difflib）
# ══════════════════════════════════════════════════════════════════════
def align_sentences(
    sentences_a: list[str],
    sentences_b: list[str],
    similarity_threshold: float = 0.25,
) -> list[tuple[Optional[int], Optional[int]]]:
    """用 difflib 對齊兩組句子

    策略：
    1. 計算兩組句子的「正規化字元序列」相似度
    2. 用 SequenceMatcher 找最佳對齊
    3. 回傳 (idx_a, idx_b) 對清單；None 表示該位置無對應

    Returns:
        [(0, 0), (1, 1), (2, None), (None, 2), (3, 3), ...]
    """
    if not sentences_a and not sentences_b:
        return []
    if not sentences_a:
        return [(None, i) for i in range(len(sentences_b))]
    if not sentences_b:
        return [(i, None) for i in range(len(sentences_a))]

    # 正規化供比對
    norm_a = [normalize_for_cer(s) for s in sentences_a]
    norm_b = [normalize_for_cer(s) for s in sentences_b]

    # 用 SequenceMatcher 找相似的 pair
    # 為每個 A 的句子找 B 中最相似的
    used_b = set()
    alignment: list[tuple[Optional[int], Optional[int]]] = []

    for i, a in enumerate(norm_a):
        best_j = None
        best_ratio = 0.0
        for j, b in enumerate(norm_b):
            if j in used_b:
                continue
            # 優先考慮相近索引位置（若相似度接近）
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            # 位置加權：差距越小加權越高
            position_bonus = max(0, 0.1 - abs(i - j) * 0.02)
            weighted = ratio + position_bonus
            if weighted > best_ratio:
                best_ratio = weighted
                best_j = j
        if best_j is not None and best_ratio >= similarity_threshold:
            alignment.append((i, best_j))
            used_b.add(best_j)
        else:
            alignment.append((i, None))

    # 加入未被對齊的 B
    for j in range(len(norm_b)):
        if j not in used_b:
            alignment.append((None, j))

    # 依原始順序排序
    def sort_key(pair):
        i, j = pair
        if i is not None and j is not None:
            return (i + j) / 2
        if i is not None:
            return i
        return j + 0.5  # B_only 稍後於同索引
    alignment.sort(key=sort_key)

    return alignment


# ══════════════════════════════════════════════════════════════════════
# LLM 仲裁
# ══════════════════════════════════════════════════════════════════════
LLM_ARBITRATION_PROMPT = """你是台中捷運無線電通訊辨識仲裁專家。

兩個語音辨識引擎對同一段音訊產生了不同結果，請判斷哪個較正確。

原則：
1. 優先保留真實出現的術語（OCC/EDRH/G07/25/26 車 等）
2. 優先保留口語特徵（好、是、over、收到）
3. 若兩者都不對但可合併成合理版本，則輸出合併版
4. 若完全無法判斷，選字數較多的版本
5. 嚴禁新增原文沒有的內容

輸入：
引擎 A ({engine_a}): {text_a}
引擎 B ({engine_b}): {text_b}

輸出 JSON（無 markdown）：
{{
  "chosen": "A" or "B" or "merged",
  "text": "最終選擇的文字",
  "reason": "簡短說明（20 字內）"
}}
"""


def llm_arbitrate(
    text_a: str,
    text_b: str,
    engine_a: str,
    engine_b: str,
    model: str = "gemini-2.5-flash",
) -> tuple[str, str, str, Optional[str]]:
    """用 LLM 仲裁兩個引擎的衝突句子

    Returns:
        (chosen_text, chosen_source, reason, raw_response)
        chosen_source: "A" | "B" | "merged" | "fallback"
    """
    try:
        from utils.gemini_client import get_client, genai_types
    except ImportError:
        return text_a if len(text_a) >= len(text_b) else text_b, "fallback", "未安裝 google-genai 或 utils.gemini_client 不可用", None

    try:
        client = get_client()
    except ValueError:
        return text_a if len(text_a) >= len(text_b) else text_b, "fallback", "找不到 API key", None

    try:
        prompt = LLM_ARBITRATION_PROMPT.format(
            engine_a=engine_a, engine_b=engine_b,
            text_a=text_a, text_b=text_b,
        )
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        raw = (resp.text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        data = json.loads(raw)
        chosen = data.get("chosen", "A")
        text = data.get("text", text_a)
        reason = data.get("reason", "")
        return text, chosen, reason, raw
    except Exception as e:
        # fallback: 取較長者
        return (text_a if len(text_a) >= len(text_b) else text_b,
                "fallback",
                f"LLM error: {type(e).__name__}",
                None)


# ══════════════════════════════════════════════════════════════════════
# 主融合器
# ══════════════════════════════════════════════════════════════════════
class SentenceLevelFuser:
    """句子層級雙引擎融合器

    Args:
        cer_high_consistency: 高度一致門檻（< 此值取任一）
        cer_medium_diff:      中度差異門檻（< 此值取 Gemini；≥ 則 LLM 仲裁）
        prefer_for_critical:  含術語句子優先的引擎（預設 "B" 即 Gemini）
        llm_arbitration:      差異大時是否啟用 LLM 仲裁
        llm_model:            LLM 仲裁用的模型
    """

    def __init__(
        self,
        cer_high_consistency: float = _DEFAULT_HIGH_CONSISTENCY,
        cer_medium_diff: float = _DEFAULT_MEDIUM_DIFF,
        prefer_for_critical: str = "B",
        llm_arbitration: bool = False,
        llm_model: str = "gemini-2.5-flash",
        length_ratio_threshold: float = 0.8,
    ):
        """
        Args:
            length_ratio_threshold: 字數比 safety 門檻。若 min/max 字數比
                低於此值，代表一邊嚴重漏字/幻覺，直接取較長者（略過句子融合）
        """
        self.cer_high_consistency = cer_high_consistency
        self.cer_medium_diff = cer_medium_diff
        self.prefer_for_critical = prefer_for_critical.upper()
        self.llm_arbitration = llm_arbitration
        self.llm_model = llm_model
        self.length_ratio_threshold = length_ratio_threshold

    def fuse(
        self,
        text_a: str,
        text_b: str,
        engine_a: str = "engine_A",
        engine_b: str = "engine_B",
    ) -> dict:
        """執行句子層級融合

        Returns:
            {
                "transcript":          str,                # 融合後全文
                "engine_a":            str,
                "engine_b":            str,
                "sentence_count":      int,
                "sentence_decisions":  list[SentenceDecision dict],
                "stats": {
                    "rule_counts":     dict,  # 各規則命中次數
                    "source_counts":   dict,  # A/B/LLM/merged 次數
                    "avg_sentence_cer": float,
                },
            }
        """
        # ── Safety fallback: 字數差距過大時直接取較長者 ──────────────
        len_a = len(normalize_for_cer(text_a))
        len_b = len(normalize_for_cer(text_b))
        if min(len_a, len_b) > 0:
            ratio = min(len_a, len_b) / max(len_a, len_b)
            if ratio < self.length_ratio_threshold:
                chosen_text = text_a if len_a >= len_b else text_b
                chosen_engine = engine_a if len_a >= len_b else engine_b
                return {
                    "transcript": chosen_text,
                    "engine_a": engine_a,
                    "engine_b": engine_b,
                    "sentence_count": 0,
                    "sentence_decisions": [],
                    "stats": {
                        "rule_counts": {"SAFETY_FALLBACK": 1},
                        "source_counts": {chosen_engine: 1},
                        "avg_sentence_cer": 0.0,
                    },
                    "safety_fallback": {
                        "triggered": True,
                        "length_ratio": round(ratio, 3),
                        "threshold": self.length_ratio_threshold,
                        "chosen": chosen_engine,
                        "reason": (
                            f"字數比 {ratio:.2f} < {self.length_ratio_threshold}，"
                            f"代表 {engine_a if len_a < len_b else engine_b} 可能嚴重漏字，"
                            f"直接取較長者 ({chosen_engine})"
                        ),
                    },
                }

        sents_a = split_sentences(text_a)
        sents_b = split_sentences(text_b)

        alignment = align_sentences(sents_a, sents_b)

        decisions: list[SentenceDecision] = []
        final_sentences: list[str] = []

        for idx, (i, j) in enumerate(alignment):
            s_a = sents_a[i] if i is not None else ""
            s_b = sents_b[j] if j is not None else ""

            # R5: 單邊有句子
            if not s_a and not s_b:
                continue
            if not s_a:
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a="", sentence_b=s_b,
                    cer=None, decision="B_only", rule="R5_single",
                    chosen_text=s_b, has_critical=has_critical_terms(s_b),
                    notes="A 無對應句",
                ))
                final_sentences.append(s_b)
                continue
            if not s_b:
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b="",
                    cer=None, decision="A_only", rule="R5_single",
                    chosen_text=s_a, has_critical=has_critical_terms(s_a),
                    notes="B 無對應句",
                ))
                final_sentences.append(s_a)
                continue

            # 計算 CER
            cer = compute_sentence_cer(s_a, s_b)
            has_crit = has_critical_terms(s_a) or has_critical_terms(s_b)

            # R1: 含關鍵術語 → 優先取指定引擎
            if has_crit and cer > 0.05:  # CER 極小時（幾乎相同）則不需特殊處理
                chosen = s_b if self.prefer_for_critical == "B" else s_a
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b=s_b,
                    cer=round(cer, 4),
                    decision=self.prefer_for_critical,
                    rule="R1_critical", chosen_text=chosen,
                    has_critical=True,
                    notes=f"含關鍵術語，優先取 {self.prefer_for_critical}",
                ))
                final_sentences.append(chosen)
                continue

            # R2: 高度一致（CER < 15%）→ 取較完整的
            if cer < self.cer_high_consistency:
                chosen = s_a if len(s_a) >= len(s_b) else s_b
                chosen_src = "A" if len(s_a) >= len(s_b) else "B"
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b=s_b,
                    cer=round(cer, 4),
                    decision=chosen_src, rule="R2_similar",
                    chosen_text=chosen, has_critical=has_crit,
                    notes=f"高度一致，取較長者",
                ))
                final_sentences.append(chosen)
                continue

            # R3: 中度差異（15% ≤ CER < 30%）→ 取 B (Gemini)
            if cer < self.cer_medium_diff:
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b=s_b,
                    cer=round(cer, 4),
                    decision="B", rule="R3_medium",
                    chosen_text=s_b, has_critical=has_crit,
                    notes="中度差異，取 Gemini（語意較穩）",
                ))
                final_sentences.append(s_b)
                continue

            # R4: 極大差異（CER ≥ 30%）→ LLM 仲裁 or fallback
            if self.llm_arbitration:
                chosen_text, chosen_src, reason, llm_raw = llm_arbitrate(
                    s_a, s_b, engine_a, engine_b, self.llm_model
                )
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b=s_b,
                    cer=round(cer, 4),
                    decision=f"LLM_{chosen_src}", rule="R4_llm",
                    chosen_text=chosen_text, has_critical=has_crit,
                    llm_raw=llm_raw, notes=f"LLM: {reason}",
                ))
                final_sentences.append(chosen_text)
            else:
                # fallback: 取較長者
                chosen = s_a if len(s_a) >= len(s_b) else s_b
                chosen_src = "A" if len(s_a) >= len(s_b) else "B"
                decisions.append(SentenceDecision(
                    idx=idx, sentence_a=s_a, sentence_b=s_b,
                    cer=round(cer, 4),
                    decision=chosen_src, rule="R4_fallback",
                    chosen_text=chosen, has_critical=has_crit,
                    notes="極大差異，LLM 未啟用，取較長者",
                ))
                final_sentences.append(chosen)

        # 統計
        rule_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        cer_sum = 0.0
        cer_count = 0
        for d in decisions:
            rule_counts[d.rule] = rule_counts.get(d.rule, 0) + 1
            source_counts[d.decision] = source_counts.get(d.decision, 0) + 1
            if d.cer is not None:
                cer_sum += d.cer
                cer_count += 1

        return {
            "transcript": " ".join(final_sentences),
            "engine_a": engine_a,
            "engine_b": engine_b,
            "sentence_count": len(decisions),
            "sentence_decisions": [asdict(d) for d in decisions],
            "stats": {
                "rule_counts": rule_counts,
                "source_counts": source_counts,
                "avg_sentence_cer": round(cer_sum / cer_count, 4) if cer_count else 0.0,
            },
        }


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text-a", required=True, help="引擎 A 的 STT 結果（檔案或字串）")
    p.add_argument("--text-b", required=True, help="引擎 B 的 STT 結果（檔案或字串）")
    p.add_argument("--engine-a", default="engine_A")
    p.add_argument("--engine-b", default="engine_B")
    p.add_argument("--llm", action="store_true", help="啟用 LLM 仲裁（CER ≥ 30% 的句子）")
    p.add_argument("--llm-model", default="gemini-2.5-flash")
    p.add_argument("--prefer-critical", default="B", choices=["A", "B"],
                   help="含關鍵術語句子優先的引擎（預設 B）")
    p.add_argument("--length-ratio", type=float, default=0.8,
                   help="字數比 safety 門檻（預設 0.8，<此值直接取較長者）")
    p.add_argument("--force-fuse", action="store_true",
                   help="跳過 safety fallback，強制進行句子層級融合")
    p.add_argument("--gt", help="若指定則比對 GT 計算融合後 CER")
    p.add_argument("--output", help="輸出 JSON 路徑（預設 stdout）")
    args = p.parse_args()

    # 讀取 text
    def _load(x):
        path = Path(x)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return x

    text_a = _load(args.text_a)
    text_b = _load(args.text_b)

    fuser = SentenceLevelFuser(
        prefer_for_critical=args.prefer_critical,
        llm_arbitration=args.llm,
        llm_model=args.llm_model,
        length_ratio_threshold=0.0 if args.force_fuse else args.length_ratio,
    )
    result = fuser.fuse(text_a, text_b, args.engine_a, args.engine_b)

    # 顯示結果
    print(f"🔀 句子層級融合完成")
    print(f"   引擎 A: {args.engine_a}")
    print(f"   引擎 B: {args.engine_b}")
    print(f"   LLM 仲裁: {'✅' if args.llm else '❌'}")
    print(f"   句子總數: {result['sentence_count']}")
    print()
    print(f"   規則統計: {result['stats']['rule_counts']}")
    print(f"   來源統計: {result['stats']['source_counts']}")
    print(f"   平均句 CER: {result['stats']['avg_sentence_cer']*100:.2f}%")
    print()

    # 若有 GT 則計算融合後 CER
    if args.gt:
        gt_path = Path(args.gt)
        if gt_path.exists():
            gt = gt_path.read_text(encoding="utf-8")
            gt_norm = normalize_for_cer(re.sub(r"^[A-Z?]:\s*", "", gt, flags=re.MULTILINE))
            cer_a = jiwer.cer(gt_norm, normalize_for_cer(text_a))
            cer_b = jiwer.cer(gt_norm, normalize_for_cer(text_b))
            cer_fused = jiwer.cer(gt_norm, normalize_for_cer(result["transcript"]))
            print(f"   📊 對照 GT 結果：")
            print(f"      {args.engine_a:15} CER = {cer_a*100:6.2f}%")
            print(f"      {args.engine_b:15} CER = {cer_b*100:6.2f}%")
            print(f"      {'fused':15} CER = {cer_fused*100:6.2f}%")
            best = min(cer_a, cer_b)
            delta = best - cer_fused
            sign = "↓" if delta > 0 else ("↑" if delta < 0 else "—")
            print(f"      vs best single: {delta*100:+.2f}% {sign}")
            result["gt_comparison"] = {
                "engine_a_cer": round(cer_a, 4),
                "engine_b_cer": round(cer_b, 4),
                "fused_cer": round(cer_fused, 4),
                "delta_vs_best": round(delta, 4),
            }

    # 寫出 JSON
    if args.output:
        Path(args.output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n📄 結果已存: {args.output}")
    else:
        print(f"\n── 融合後文字 ──")
        print(result["transcript"])


if __name__ == "__main__":
    main()
