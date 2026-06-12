#!/usr/bin/env python3
"""
站碼閉集約束修正器 (StationCodeCorrector)
==========================================
版本: 1.0.0 (2026-06-12) — 北屯機廠根因調查任務 4

綠線站碼 G0–G17（含 8a/10a）是封閉集合，且「站碼 + 站名」常成對出現，
可互為錨點交叉驗證。兩條規則：

  Rule N（站名錨定，修站碼）：
      站名完全命中已知站名、但站碼不符 → 信站名、改站碼。
      例：「G07高鐵站」→「G17高鐵站」（實測 ×27，雙音節站名在
      無線電噪訊下遠比單音節數字可靠）。

  Rule F（站碼錨定，修站名）：
      站碼是某站的合法碼、站名與該站正名同長且僅差 1 字 → 信站碼、改站名。
      例：「G05市維站」→「G05四維站」、「G00北平站」→「G00北屯站」。

安全邊界（缺一不可，背景見 2026-06-12 北屯根因調查 devlog）：
  1. 補零不動：GT 慣例本身 G9/G09、G0/G00 混用，僅差補零視為相同。
  2. 站名表用 GT 實際慣例（G7=中清、G8=文華…），不可引用
     master_vocabulary.csv 的站碼表（該表與營運實際用法不符）。
  3. 模糊對碰跳過：兩規則都可解釋（如「G11北屯站」可解為
     南屯誤聽或站碼誤聽，南屯/北屯僅差 1 字）→ 不修。
  4. 站碼站名皆錯（如「G94五站」）→ 不修，留給 LLM 層。

用法：
    from scripts.station_code_corrector import correct_station_codes
    text, changes = correct_station_codes("OCC通告G07高鐵站")
"""

from __future__ import annotations

import re

# ── 站名 → 站碼數字部（GT 實際慣例，自 260603/260604 等批次 GT 統計） ──
# 注意：與 master_vocabulary.csv 的站碼表「不同」——該表 G06=中清、
# G07=文華與營運用法錯位，本表以 GT 為準。
STATION_CANON: dict[str, str] = {
    "北屯": "0",
    "舊社": "3",
    "松竹": "4",
    "四維": "5",
    "崇德": "6",
    "中清": "7",
    "文華": "8",
    "櫻花": "8a",
    "市府": "9",
    "水安": "10",
    "森林": "10a",
    "南屯": "11",
    "豐樂": "12",
    "大慶": "13",
    "九張犁": "14",
    "九德": "15",
    "烏日": "16",
    "高鐵": "17",
}
_CODE_TO_NAME: dict[str, str] = {v: k for k, v in STATION_CANON.items()}

# 站碼 + 可選空格 + 可選站名 + 「站」
# 站碼數字部最多 3 位（涵蓋 G945 這類誤辨），站名 1–4 個中文字
_PAT = re.compile(
    r"(?P<prefix>[GgRr])(?P<num>\d{1,3})(?P<sub>[aA]?)"
    r"(?P<gap> ?)(?P<name>[一-鿿]{1,4}?)站"
)


def _canon_num(num: str, sub: str) -> str:
    """站碼數字部正規化：去前導零 + 子碼小寫（G09 → 9、G08A → 8a）。"""
    stripped = num.lstrip("0") or "0"
    return stripped + sub.lower()


def _restore_padding(canon: str, orig_num: str) -> str:
    """改寫站碼時保留原輸出的補零寬度（G01→G07 而非 G7），降低與 GT 慣例的摩擦。

    寬度上限 2：合法站碼數字部最多兩位，三位寬的誤辨（G107）不還原成
    不存在的三位形式（G017），收斂到 G17。
    """
    m = re.match(r"(\d+)([a-z]?)", canon)
    digits, sub = m.group(1), m.group(2)
    width = min(len(orig_num), 2)
    if width > len(digits):
        digits = digits.zfill(width)
    return digits + sub


def _hamming1(a: str, b: str) -> bool:
    """同長且恰差 1 字。"""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def correct_station_codes(text: str) -> tuple[str, list[dict]]:
    """站碼/站名交叉驗證修正。回傳 (修正後文字, 修正紀錄)。"""
    if not text:
        return text, []

    changes: list[dict] = []

    def _repl(m: re.Match) -> str:
        prefix, num, sub = m.group("prefix"), m.group("num"), m.group("sub")
        gap, name = m.group("gap"), m.group("name")
        code = _canon_num(num, sub)
        original = m.group(0)

        # Rule N：站名完全命中 → 站碼必須是該站的碼
        if name in STATION_CANON:
            want = STATION_CANON[name]
            if code == want:
                return original  # 已正確（含補零差異）
            # 模糊對碰：站碼本身也是合法碼，且其正名與觀測站名僅差 1 字
            # （如 G11北屯站：南屯/北屯難分）→ 不修
            canon_name = _CODE_TO_NAME.get(code)
            if canon_name is not None and _hamming1(canon_name, name):
                return original
            fixed_code = _restore_padding(want, num)
            fixed = f"{prefix}{fixed_code}{gap}{name}站"
            changes.append({
                "from": original, "to": fixed,
                "rule": "station_name_anchor",
            })
            return fixed

        # Rule F：站碼合法 → 站名與正名同長僅差 1 字才修
        canon_name = _CODE_TO_NAME.get(code)
        if canon_name is not None and _hamming1(canon_name, name):
            fixed = f"{prefix}{num}{sub}{gap}{canon_name}站"
            changes.append({
                "from": original, "to": fixed,
                "rule": "station_code_anchor",
            })
            return fixed

        return original

    result = _PAT.sub(_repl, text)
    return result, changes


# ── CLI 自測 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    cases = [
        ("OCC通告G07高鐵站", "OCC通告G17高鐵站"),          # Rule N
        ("請G05市維站回報", "請G05四維站回報"),              # Rule F
        ("G00北平站收到", "G00北屯站收到"),                  # Rule F
        ("G09市府站正常", "G09市府站正常"),                  # 補零不動
        ("G11北屯站", "G11北屯站"),                          # 模糊對碰不修
        ("G94五站", "G94五站"),                              # 雙錯不修
        ("G17 高鐵站", "G17 高鐵站"),                        # 帶空格已正確
    ]
    failed = 0
    for src, want in cases:
        got, _ = correct_station_codes(src)
        ok = got == want
        failed += not ok
        print(f"{'✅' if ok else '❌'} {src!r} → {got!r}" + ("" if ok else f"（預期 {want!r}）"))
    sys.exit(1 if failed else 0)
