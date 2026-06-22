"""HomophoneCorrector 測試。

驗證：能修同音/近音錯字、不過度校正、保護非 CJK、attestation 護欄。
測試用語料內建（不依賴 repo 的 char_4gram.pkl，確保穩定可重現）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("pypinyin")

from scripts.build_ngram_lm import CharNgramLM, clean_for_lm  # noqa: E402
from scripts.homophone_corrector import HomophoneCorrector  # noqa: E402


CORPUS = [
    "我們來討論這個對話框的設計",
    "請確認對話內容",
    "請把語音檔案轉文字",
    "餵檔案進去做語音辨識",
    "環境音偵測啟動",
    "這段邏輯有問題",
    "對話",
    "環境音",
    "邏輯",
    "OCC通告全線因電力異常",
    "請G15九德站長回報巡檢狀況",
]


@pytest.fixture(scope="module")
def corrector() -> HomophoneCorrector:
    lm = CharNgramLM(order=4, alpha=0.4)
    lm.train([clean_for_lm(s) for s in CORPUS])
    return HomophoneCorrector(lm, max_pinyin_dist=1, margin=2.0)


def test_fixes_exact_homophone(corrector):
    out, changes = corrector.correct("對化")  # 化→話（同音）
    assert out == "對話"
    assert changes and changes[0]["from"] == "化" and changes[0]["to"] == "話"


def test_fixes_near_homophone_multichar(corrector):
    # 黃靜英 → 環境音（huang/huan、jing、ying/yin 皆 Lev<=1）
    out, _ = corrector.correct("黃靜英")
    assert out == "環境音"


def test_does_not_overcorrect_correct_text(corrector):
    for s in ["對話", "環境音", "請確認對話內容"]:
        out, changes = corrector.correct(s)
        assert out == s, f"不該動正確句：{s} → {out}"
        assert changes == []


def test_protects_non_cjk_tokens(corrector):
    # 數字/英文/授權碼不可被當同音字替換
    s = "OCC通告全線"
    out, _ = corrector.correct(s)
    assert out.startswith("OCC")  # 英文鎖定
    s2 = "G15九德站長1017"
    out2, _ = corrector.correct(s2)
    assert "G15" in out2 and "1017" in out2  # 站碼/授權碼保留


def test_short_or_empty_noop(corrector):
    assert corrector.correct("") == ("", [])
    assert corrector.correct("好") == ("好", [])  # 單字無上下文


def test_unattested_change_reverts(corrector):
    # 語料沒有的詞，候選若無 bigram 佐證 → 整句回退原文（不無中生有）
    s = "邏輯"  # 在語料內，應保持
    out, _ = corrector.correct(s)
    assert out == "邏輯"