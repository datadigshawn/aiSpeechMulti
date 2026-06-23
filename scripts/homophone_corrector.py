"""同音/近音選字校正器（語言層，char n-gram rescoring）。

針對 SenseVoice 等非自迴歸模型的「聽對音、挑錯字」錯誤：對 final 文字做
fuzzy 拼音同音候選展開 + char n-gram 重排，選回域內最可能的字。

設計（即時路徑安全閘）：
- 純 deterministic：char n-gram 打分，微秒級，無 LLM 延遲/成本。
- 只動 CJK 字；數字/英文/標點/授權碼等非 CJK 位置鎖定不變。
- margin 護欄：corrected 必須比 original 機率高過 `margin`(log10) 才替換。
- attestation 護欄：被改的字必須與鄰字組成「語料真的出現過」的 bigram，
  否則整句回退原文 —— 不無中生有、不對 OOV 亂改。
- 涵蓋範圍取決於 LM 語料；語料涵蓋不到的詞會安全地不動（no-op）。

可行性驗證見 _decisions/2026-06-12 選字問題策略 — 辭典 vs 語言模型。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from pypinyin import Style, pinyin
    _PYPINYIN_OK = True
except Exception:  # pragma: no cover - 套件未裝時整個校正器停用
    _PYPINYIN_OK = False


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# 中文數字等保護字：不可被當同音字校正（避免把數字/量詞改爛）。
# 即時路徑通常已把數字正規化成阿拉伯數字，此為離線/防呆雙保險。
_PROTECTED_CHARS = frozenset("零一二三四五六七八九十百千萬億兩○〇壹貳參肆伍陸柒捌玖拾佰仟")


def _lev(a: str, b: str) -> int:
    """字串 Levenshtein 距離（給拼音字串用）。"""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if not m or not n:
        return m or n
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[n]


class HomophoneCorrector:
    """以 char n-gram LM 對同音/近音錯字做 rescoring 校正。"""

    def __init__(
        self,
        lm,
        *,
        max_pinyin_dist: int = 1,
        margin: float = 2.0,
        beam: int = 15,
        min_len: int = 2,
        terms: "list[str] | None" = None,
        term_bonus: float = 6.0,
        term_margin: float = 0.0,
        general_correction: bool = False,
    ) -> None:
        self.lm = lm
        self.max_pinyin_dist = max_pinyin_dist
        self.margin = margin
        self.beam = beam
        self.min_len = min_len
        # 域術語表（保護＋偏好）。≥2 字才有意義。
        self._terms = frozenset(t for t in (terms or ()) if t and len(t) >= 2)
        self._max_term_len = max((len(t) for t in self._terms), default=0)
        # rescoring 對「形成術語」的每字加分；須大於 LM 對 OOV 字的 floor 懲罰
        # （≈5/字）才能蓋過稀有術語字的低分。
        self.term_bonus = term_bonus
        self.term_margin = term_margin     # 形成術語時可接受的最小 LM 增益
        # general_correction：是否允許「自由同音改寫」(非術語)。
        # 實測（稠密域內 LM）此路徑誤改率 28~63%、且 recall 不穩 → 預設 OFF，
        # 只保留「只修成已知術語」的安全子集（held-out 誤改率 0%）。
        self.general_correction = general_correction
        # 候選池 = LM vocab 內的 CJK 字（確保候選都打得出分）
        self._pool = [c for c in self._lm_vocab() if _is_cjk(c)]
        self._pinyin_of: dict[str, str] = {c: _toneless(c) for c in self._pool}
        # pinyin -> 同音字（vocab 內）
        self._by_pinyin: dict[str, list[str]] = {}
        for c, py in self._pinyin_of.items():
            if py:
                self._by_pinyin.setdefault(py, []).append(c)
        self._uniq_pinyins = list(self._by_pinyin.keys())

    # ---- 載入 ----
    @classmethod
    def from_pickle(
        cls,
        pkl_path: Path | str,
        *,
        terms_path: Path | str | None = None,
        **kw,
    ) -> Optional["HomophoneCorrector"]:
        """從 build_ngram_lm 產生的 .pkl 載入；缺套件/缺檔回 None。

        terms_path：域術語清單（一行一詞，純中文）；缺檔則不啟用術語保護/偏好。
        """
        if not _PYPINYIN_OK:
            return None
        pkl_path = Path(pkl_path)
        if not pkl_path.exists():
            return None
        import pickle
        from scripts.build_ngram_lm import CharNgramLM

        class _Unpickler(pickle.Unpickler):
            # char_4gram.pkl 由 `python build_ngram_lm.py` 產生，類別被存成
            # __main__.CharNgramLM；這裡無論來源模組一律映射回真正的類別。
            def find_class(self, module, name):
                if name == "CharNgramLM":
                    return CharNgramLM
                return super().find_class(module, name)

        with open(pkl_path, "rb") as f:
            lm = _Unpickler(f).load()

        terms = kw.pop("terms", None)
        if terms_path:
            tp = Path(terms_path)
            if tp.exists():
                terms = [ln.strip() for ln in tp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return cls(lm, terms=terms, **kw)

    # ---- 內部 ----
    def _lm_vocab(self) -> list[str]:
        # CharNgramLM 的 1-gram keys 為單字 tuple
        uni = getattr(self.lm, "ngrams", {}).get(1, {})
        return [t[0] for t in uni.keys() if isinstance(t, tuple) and len(t) == 1]

    @lru_cache(maxsize=4096)
    def _candidates(self, ch: str) -> tuple[str, ...]:
        if not _is_cjk(ch):
            return (ch,)
        target = _toneless(ch)
        if not target:
            return (ch,)
        out = {ch}
        for py in self._uniq_pinyins:
            if _lev(py, target) <= self.max_pinyin_dist:
                out.update(self._by_pinyin[py])
        # 不把保護字（中文數字等）當成替換候選
        out = {c for c in out if c == ch or c not in _PROTECTED_CHARS}
        return tuple(out)

    def _bigram_attested(self, a: str, b: str) -> bool:
        return (a, b) in self.lm.ngrams.get(2, {})

    def _term_cover(self, s: str) -> set[int]:
        """回傳 s 中被任一域術語覆蓋的字元位置（由左greedy取最長匹配）。"""
        if not self._terms:
            return set()
        cover: set[int] = set()
        i, n = 0, len(s)
        while i < n:
            matched = 0
            for length in range(min(self._max_term_len, n - i), 1, -1):
                if s[i:i + length] in self._terms:
                    matched = length
                    break
            if matched:
                cover.update(range(i, i + matched))
                i += matched
            else:
                i += 1
        return cover

    def correct(self, text: str) -> tuple[str, list[dict]]:
        """回傳 (corrected_text, changes)。changes 為空表示未改。"""
        if not _PYPINYIN_OK or not text or len(text) < self.min_len:
            return text, []
        if not any(_is_cjk(c) for c in text):
            return text, []

        # 保護：輸入中已正確出現的域術語，其位置鎖定不動
        locked = self._term_cover(text)

        # 偏好：rescoring 目標 = LM + 形成術語的加分
        def _objective(s: str) -> float:
            v = self.lm.log10_prob(s)
            if self._terms and self.term_bonus:
                v += self.term_bonus * len(self._term_cover(s))
            return v

        # beam rescoring：非 CJK / 保護字（數字）/ 受保護術語位置鎖定，其餘展開同音候選
        beams = [text]
        for i, ch in enumerate(text):
            if i in locked or ch in _PROTECTED_CHARS:
                continue
            cands = self._candidates(ch)
            if len(cands) == 1:
                continue
            nxt = []
            for b in beams:
                for c in cands:
                    nxt.append(b[:i] + c + b[i + 1:])
            nxt = sorted(set(nxt), key=_objective, reverse=True)[: self.beam]
            beams = nxt

        best = max(beams, key=_objective)
        if best == text:
            return text, []

        changed = [i for i, (o, n) in enumerate(zip(text, best)) if o != n]
        lm_gain = self.lm.log10_prob(best) - self.lm.log10_prob(text)

        # 接受路徑 B（偏好）：所有變更都落在 best 的某個域術語內，且 LM 未更差
        if self._terms:
            best_cover = self._term_cover(best)
            if changed and all(i in best_cover for i in changed) and lm_gain >= self.term_margin:
                return best, [
                    {"pos": i, "from": text[i], "to": best[i], "via": "term"} for i in changed
                ]

        # 接受路徑 A（自由同音改寫）：margin 護欄 + attestation 護欄。
        # 預設停用（誤改率過高）；僅實驗用 general_correction=True 才啟用。
        if not self.general_correction:
            return text, []
        if lm_gain < self.margin:
            return text, []
        changes = []
        for i in changed:
            o, n = text[i], best[i]
            left_ok = i > 0 and self._bigram_attested(best[i - 1], n)
            right_ok = i < len(best) - 1 and self._bigram_attested(n, best[i + 1])
            if not (left_ok or right_ok):
                return text, []  # 有任一被改字無語料佐證 → 整句回退
            changes.append({"pos": i, "from": o, "to": n})

        return best, changes


@lru_cache(maxsize=8192)
def _toneless_impl(ch: str) -> str:
    try:
        return pinyin(ch, style=Style.NORMAL, errors="ignore")[0][0]
    except Exception:
        return ""


def _toneless(ch: str) -> str:
    if not _PYPINYIN_OK:
        return ""
    return _toneless_impl(ch)


def _main() -> None:  # pragma: no cover - CLI 手動驗證用
    import argparse
    ap = argparse.ArgumentParser(description="同音選字校正器（離線測試）")
    ap.add_argument("--lm", required=True, help="char n-gram .pkl 路徑")
    ap.add_argument("--text", required=True, help="待校正文字")
    ap.add_argument("--margin", type=float, default=2.0)
    ap.add_argument("--max-dist", type=int, default=1)
    args = ap.parse_args()
    hc = HomophoneCorrector.from_pickle(args.lm, margin=args.margin, max_pinyin_dist=args.max_dist)
    if hc is None:
        print("校正器不可用（缺 pypinyin 或 .pkl）")
        return
    corrected, changes = hc.correct(args.text)
    print(f"原文: {args.text}")
    print(f"校正: {corrected}")
    print(f"變更: {changes}")


if __name__ == "__main__":
    _main()