"""Tests for scripts/batch_stt_eval.make_engine — 確認已委派單一工廠 create_engine
（2026-06-18 tech-debt B-3：引擎工廠收斂）。

以 patch create_engine 驗證 label → (name, opts) 路由，不真初始化引擎。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import scripts.batch_stt_eval as bse


@pytest.mark.parametrize("label, exp_name, exp_model", [
    ("chirp3",      "chirp3",     "chirp_3"),
    ("gemini",      "gemini",     "gemini-2.5-flash"),
    ("gemini25pro", "gemini",     "gemini-2.5-pro"),
    ("gemini31pro", "gemini",     "gemini-3.1-pro-preview"),
])
def test_make_engine_delegates_with_model(label, exp_name, exp_model):
    with patch("scripts.models.factory.create_engine") as ce:
        bse.make_engine(label)
        ce.assert_called_once()
        name = ce.call_args.args[0]
        kwargs = ce.call_args.kwargs
        assert name == exp_name
        assert kwargs["model"] == exp_model


@pytest.mark.parametrize("label, exp_name", [
    ("scribe", "scribe"),
    ("sensevoice", "sensevoice"),
])
def test_make_engine_delegates_simple(label, exp_name):
    with patch("scripts.models.factory.create_engine") as ce:
        bse.make_engine(label)
        ce.assert_called_once_with(exp_name, **ce.call_args.kwargs)
        assert ce.call_args.args[0] == exp_name


def test_unknown_label_raises():
    with pytest.raises(ValueError):
        bse.make_engine("nope")
