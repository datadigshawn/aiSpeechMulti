"""Pricing 載入與成本計算。

純函數設計：所有 entry 都接受 pricing dict（或 None 用預設）。
這樣測試可以注入自訂 pricing 不用改檔，prod 用預設。
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICING_PATH = PROJECT_ROOT / "config" / "pricing.json"


class PricingError(ValueError):
    """pricing.json 結構或單位不合法。"""


def load_pricing(path: Path | None = None) -> dict:
    """讀 pricing.json 並回傳 dict。失敗或結構不完整 raise PricingError。"""
    p = Path(path) if path else DEFAULT_PRICING_PATH
    if not p.exists():
        raise PricingError(f"pricing.json not found at {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PricingError(f"pricing.json malformed: {e}") from e

    # 必要 top-level keys
    for required in ("usd_to_twd", "engines"):
        if required not in data:
            raise PricingError(f"pricing.json missing required key '{required}'")

    # 各引擎的必要 keys：unit 必備；費率允許兩種計價模型
    #   - STT 單費率：usd_per_unit（搭配 unit=audio_seconds，calc_cost 使用）
    #   - LLM 雙費率：usd_per_1m_in + usd_per_1m_out（搭配 unit=tokens，speech_report 使用）
    for engine_name, cfg in data["engines"].items():
        if "unit" not in cfg:
            raise PricingError(
                f"engine '{engine_name}' config missing required key 'unit'"
            )
        has_flat_rate = "usd_per_unit" in cfg
        has_io_rate = "usd_per_1m_in" in cfg and "usd_per_1m_out" in cfg
        if not (has_flat_rate or has_io_rate):
            raise PricingError(
                f"engine '{engine_name}' config needs 'usd_per_unit' "
                f"or both 'usd_per_1m_in' and 'usd_per_1m_out'"
            )

    return data


def calc_cost(engine: str, usage: dict, pricing: dict) -> tuple[float, float]:
    """算單次呼叫的 USD / TWD 成本。

    Args:
        engine: 引擎 key（必須在 pricing["engines"] 裡）
        usage: usage dict，例如 {"audio_seconds": 87.3} 或 {"input_tokens": ..., "output_tokens": ...}
        pricing: 完整 pricing dict（load_pricing() 回傳的，已驗證結構）

    Returns:
        (cost_usd, cost_twd)
    """
    engines = pricing.get("engines", {})
    if engine not in engines:
        raise PricingError(f"engine '{engine}' not in pricing.json")
    cfg = engines[engine]
    unit = cfg["unit"]
    rate = cfg["usd_per_unit"]
    qty = usage.get(unit)
    if qty is None:
        raise PricingError(f"usage missing required key '{unit}' for engine '{engine}'")
    cost_usd = float(qty) * float(rate)
    cost_twd = cost_usd * float(pricing["usd_to_twd"])  # load_pricing 已驗證此 key 存在
    return cost_usd, cost_twd


def alert_level(today_total_twd: float, pricing: dict) -> str:
    """依 daily_budget_twd 與 pct 閾值決定警告等級。

    Returns: "ok" | "warning" | "critical"
    """
    alerts = pricing.get("alerts", {})
    budget = alerts.get("daily_budget_twd", 0)
    if budget <= 0:
        return "ok"  # 邊界：未設預算 → 永遠 ok
    pct = today_total_twd / budget * 100
    if pct >= alerts.get("daily_critical_pct", 100):
        return "critical"
    if pct >= alerts.get("daily_warning_pct", 80):
        return "warning"
    return "ok"
