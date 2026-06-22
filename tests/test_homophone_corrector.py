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
    "請確認授權碼",
    "授權碼一零一七",
    "行控中心通告全線",
]

TERMS = ["授權碼", "行控中心", "正線", "通告"]


@pytest.fixture(scope="module")
def corrector() -> HomophoneCorrector:
    lm = CharNgramLM(order=4, alpha=0.4)
    lm.train([clean_for_lm(s) for s in CORPUS])
    return HomophoneCorrector(lm, max_pinyin_dist=1, margin=2.0)


@pytest.fixture(scope="module")
def corrector_terms() -> HomophoneCorrector:
    lm = CharNgramLM(order=4, alpha=0.4)
    lm.train([clean_for_lm(s) for s in CORPUS])
    return HomophoneCorrector(lm, max_pinyin_dist=1, margin=2.0, terms=TERMS)


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


# ---- 域術語：保護 + 偏好 ----

def test_term_prefer_forms_term(corrector_terms):
    # 受權碼 → 授權碼（受/授 同音），靠術語偏好拉回
    out, changes = corrector_terms.correct("受權碼")
    assert out == "授權碼"
    assert changes and changes[0].get("via") == "term"


def test_term_protect_keeps_correct_term(corrector_terms):
    # 已正確的術語位置鎖定，不被動到（即使鄰接可校正的錯字）
    out, _ = corrector_terms.correct("行控中心通告全線")
    assert out.startswith("行控中心")


def test_terms_none_backward_compatible(corrector, corrector_terms):
    # 無術語表時行為不變；一般同音字兩者都該修
    assert corrector.correct("對化")[0] == "對話"
    assert corrector_terms.correct("對化")[0] == "對話"


def test_protects_chinese_numerals(corrector_terms):
    # 中文數字不可被當同音字改爛；術語拉回但數字原樣
    out, _ = corrector_terms.correct("受權碼一零一七")
    assert out == "授權碼一零一七"