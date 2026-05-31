"""
SenseVoiceSmall + LoRA fine-tuned 語音辨識模組（捷運通訊專用）
==============================================================

延伸自 model_sensevoice.SenseVoiceModel；載入後在底層 funasr AutoModel 上
套用 PEFT LoRA wrapper 並注入訓練好的 lora_state_dict（best.pt）。

預設 checkpoint：
    experiments/finetune_runs/sensevoice_lora_r32_e60/best.pt

訓練設定（與 _inference_finetuned_all.py 一致）：
    rank=32, alpha=64, dropout=0.05, bias="none"
    target_modules: q/k/v/out_proj + linear_q/k/v/out
    task_type: FEATURE_EXTRACTION

CER 表現（2026-05-01 全 63 段）：
    raw 29.50% / +car_norm+dict+llm 28.12%
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .model_sensevoice import SenseVoiceModel

logger = logging.getLogger(__name__)


# ── 預設 checkpoint 與 LoRA 設定（與訓練一致）──────────────────────────────
# v2_157gt: 2026-05-31 訓練（113 段，test CER 25.42% with +llm）
# legacy r32_e60: 2026-05-01 訓練（46 段，test CER 28.12% with +llm）
_DEFAULT_CKPT = (
    Path(__file__).resolve().parents[2]
    / "experiments" / "finetune_runs" / "sensevoice_lora_r32_e60_v2_157gt" / "best.pt"
)
_DEFAULT_LORA = {
    "r": 32,
    "lora_alpha": 64,
    "target_modules": [
        "q_proj", "k_proj", "v_proj", "out_proj",
        "linear_q", "linear_k", "linear_v", "linear_out",
    ],
    "lora_dropout": 0.05,
    "bias": "none",
}


class SenseVoiceFTModel(SenseVoiceModel):
    """
    Fine-tuned SenseVoiceSmall（套 LoRA checkpoint）。

    與父類 API 完全相同；差別在 _ensure_loaded 後會把 self._model.model 換成
    PEFT 包裝的版本並載入 lora_state_dict。

    Args（除父類外新增）：
        ckpt_path:   LoRA checkpoint 路徑（best.pt），預設 r32_e60。
        lora_config: 自訂 LoRA 設定（rank/alpha/target_modules）。
    """

    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "zh",
        device: str = "cpu",
        vocabulary_csv: Optional[str] = None,
        use_vad: bool = True,
        ckpt_path: Optional[str | Path] = None,
        lora_config: Optional[dict] = None,
    ):
        super().__init__(
            model_name=model_name,
            language=language,
            device=device,
            vocabulary_csv=vocabulary_csv,
            use_vad=use_vad,
        )
        self._ckpt_path = Path(ckpt_path) if ckpt_path else _DEFAULT_CKPT
        self._lora_cfg_kwargs = lora_config or _DEFAULT_LORA
        self._lora_loaded = False

    def _ensure_loaded(self):
        super()._ensure_loaded()
        if self._lora_loaded:
            return

        if not self._ckpt_path.exists():
            raise FileNotFoundError(
                f"找不到 LoRA checkpoint：{self._ckpt_path}\n"
                "請先在 GPU 機台執行 fine-tune（scripts/finetune_sensevoice.py）"
                "或從訓練機複製 best.pt 至上述路徑。"
            )

        try:
            import torch
            from peft import (
                LoraConfig, get_peft_model, TaskType, set_peft_model_state_dict,
            )
        except ImportError as e:
            raise ImportError(
                "fine-tuned 模式需要 peft 套件：pip install peft"
            ) from e

        logger.info(f"載入 LoRA checkpoint: {self._ckpt_path}")
        state = torch.load(self._ckpt_path, map_location=self.device, weights_only=False)

        lora_config = LoraConfig(
            **self._lora_cfg_kwargs,
            task_type=TaskType.FEATURE_EXTRACTION,
        )
        wrapped = get_peft_model(self._model.model, lora_config)
        set_peft_model_state_dict(wrapped, state["lora_state_dict"])
        self._model.model = wrapped
        self._lora_loaded = True
        logger.info("✅ fine-tuned SenseVoice 模型就緒")
