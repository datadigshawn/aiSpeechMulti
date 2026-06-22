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
    ) -> None:
        self.lm = lm
        self.max_pinyin_dist = max_pinyin_dist
        self.margin = margin
        self.beam = beam
        self.min_len = min_len
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
    def from_pickle(cls, pkl_path: Path | str, **kw) -> Optional["HomophoneCorrector"]:
        """從 build_ngram_lm 產生的 .pkl 載入；缺套件/缺檔回 None。"""
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
        return cls(lm, **kw)

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
        return tuple(out)

    def _bigram_attested(self, a: str, b: str) -> bool:
        return (a, b) in self.lm.ngrams.get(2, {})

    def correct(self, text: str) -> tuple[str, list[dict]]:
        """回傳 (corrected_text, changes)。changes 為空表示未改。"""
        if not _PYPINYIN_OK or not text or len(text) < self.min_len:
            return text, []
        if not any(_is_cjk(c) for c in text):
            return text, []

        # beam rescoring：非 CJK 位置鎖定，CJK 位置展開同音候選
        beams = [text]
        for i, ch in enumerate(text):
            cands = self._candidates(ch)
            if len(cands) == 1:
                continue
            nxt = []
            for b in beams:
                for c in cands:
                    nxt.append(b[:i] + c + b[i + 1:])
            nxt = sorted(set(nxt), key=self.lm.log10_prob, reverse=True)[: self.beam]
            beams = nxt

        best = max(beams, key=self.lm.log10_prob)
        if best == text:
            return text, []

        # margin 護欄
        if self.lm.log10_prob(best) - self.lm.log10_prob(text) < self.margin:
            return text, []

        # attestation 護欄：每個被改的字都要與鄰字組成語料出現過的 bigram
        changes = []
        for i, (o, n) in enumerate(zip(text, best)):
            if o == n:
                continue
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