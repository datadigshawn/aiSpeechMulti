#!/usr/bin/env python3
"""
數字與編號正規化擴充模組 (NumberNormalizer)
==============================================
版本: 1.0.0 (2026-04-08)

擴充 car_number_normalizer，新增以下正規化功能：

1. **時間正規化** (time_normalization)
   - 十四時三十分 → 14:30
   - 下午兩點半 → 14:30
   - 二十三時零五分 → 23:05
   - 腰四點三零 → 14:30 (軍事讀法)

2. **站碼補零** (station_code_padding)
   - G7 → G07
   - R1 → R01
   - G0 → G00
   - 保留已標準的 G07、R15 不變

3. **數字邊界空格正規化** (number_spacing)
   - 月台前後: 二月台 → 2 月台、三月台 → 3 月台
   - 通用: 數字黏在中文旁 → 加空格

4. **時長/距離正規化** (duration_normalization)
   - 五分鐘 → 5 分鐘
   - 十秒 → 10 秒

設計原則：
- **保守**：不確定時保留原文
- **分段安全**：每個正規化都是獨立 pass，失敗不影響其他
- **可觀測**：回傳 changes 清單方便除錯

用法（模組）：
    from scripts.number_normalizer import normalize_numbers

    text, changes = normalize_numbers(
        "下午兩點半，G7 站長呼叫，請派員到二月台待命五分鐘",
        enable_time=True,
        enable_station_code=True,
        enable_spacing=True,
        enable_duration=True,
    )
    print(text)
    # 下午 14:30，G07 站長呼叫，請派員到 2 月台待命 5 分鐘

用法（CLI）：
    python3 scripts/number_normalizer.py --test
    python3 scripts/number_normalizer.py --text "下午兩點半 G7 站長"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════════
# 中文/軍事數字對照
# ══════════════════════════════════════════════════════════════════════
DIGIT_MAP = {
    "零": "0", "〇": "0", "洞": "0",
    "一": "1", "壹": "1", "么": "1", "腰": "1",
    "二": "2", "兩": "2", "貳": "2",
    "三": "3", "參": "3", "叁": "3",
    "四": "4", "肆": "4",
    "五": "5", "伍": "5",
    "六": "6", "陸": "6",
    "七": "7", "柒": "7", "拐": "7",
    "八": "8", "捌": "8",
    "九": "9", "玖": "9", "勾": "9",
}
_DIGIT_CLASS = "[" + "".join(DIGIT_MAP.keys()) + "0-9]"


def _chn_to_arabic(s: str) -> str:
    """單純字元替換，中文數字字元 → 阿拉伯數字"""
    return "".join(DIGIT_MAP.get(c, c) for c in s)


def _parse_chn_number(s: str) -> int | None:
    """解析中文數字為整數

    支援：
    - 純字元串（一二三四 → 1234）
    - 「十」「二十」「二十三」這類位數表示
    """
    if not s:
        return None

    # 方案 A：純字元串（適合時間的「二十三」「零五」等）
    if all(c in DIGIT_MAP or c.isdigit() for c in s):
        arabic = _chn_to_arabic(s)
        try:
            return int(arabic)
        except ValueError:
            return None

    # 方案 B：含「十」的結構化數字（0-99）
    if s == "十":
        return 10
    # "二十" → 20
    m = re.match(r"^([零一二兩三四五六七八九洞腰拐勾])十$", s)
    if m:
        d = _parse_chn_number(m.group(1))
        return d * 10 if d is not None else None
    # "十三" → 13
    m = re.match(r"^十([零一二兩三四五六七八九洞腰拐勾])$", s)
    if m:
        d = _parse_chn_number(m.group(1))
        return 10 + d if d is not None else None
    # "二十三" → 23
    m = re.match(r"^([一二兩三四五六七八九腰])十([零一二兩三四五六七八九洞])$", s)
    if m:
        tens = _parse_chn_number(m.group(1))
        ones = _parse_chn_number(m.group(2))
        if tens is not None and ones is not None:
            return tens * 10 + ones
    return None


# ══════════════════════════════════════════════════════════════════════
# 1. 時間正規化
# ══════════════════════════════════════════════════════════════════════
# 支援的時間表達：
#   十四時三十分 / 14 時 30 分
#   下午兩點半 / 兩點三十分
#   二十三時零五分
#   腰四點三零 (軍事)

_TIME_MAP_HALF = "半"
_TIME_MAP_NOON = {"中午": 12, "正午": 12}
_TIME_MAP_PM = {"下午", "晚上", "傍晚", "夜間"}
_TIME_MAP_AM = {"上午", "早上", "清晨", "凌晨"}

# 中文數字群組（含「十」支援結構化數字如「二十三」「十五」）
_CHN_NUM_GROUP = (
    r"(?:"
    r"[零一二兩三四五六七八九]{1,2}十[零一二兩三四五六七八九]"  # 二十三
    r"|[零一二兩三四五六七八九]{1,2}十"                      # 二十
    r"|十[零一二兩三四五六七八九]"                            # 十五
    r"|十"                                                 # 十
    r"|[零一二兩三四五六七八九〇洞腰么拐勾壹貳參叁肆伍陸柒捌玖]{1,2}"  # 純字元
    r"|\d{1,2}"                                            # 阿拉伯數字
    r")"
)

# 「N時 M分」或「N 點 M 分」
_TIME_PATTERN_FULL = re.compile(
    rf"(下午|上午|早上|清晨|凌晨|傍晚|夜間|中午|正午|晚上)?\s*"
    rf"({_CHN_NUM_GROUP})\s*[時點]\s*"
    rf"({_CHN_NUM_GROUP}|半)\s*分?"
)

# 「N 時整」或「N 點整」（獨立出來處理無分鐘的情況）
_TIME_PATTERN_HOUR = re.compile(
    rf"(下午|上午|早上|清晨|凌晨|傍晚|夜間|中午|正午|晚上)?\s*"
    rf"({_CHN_NUM_GROUP})\s*[時點](?:整|鐘)?"
    rf"(?![時點分\d零一二兩三四五六七八九十])"  # 後面不能接數字或時點分
)


def _adjust_hour_by_period(hour: int, period: str) -> int:
    """依 AM/PM 調整小時"""
    if period in _TIME_MAP_PM and 1 <= hour <= 11:
        return hour + 12
    if period in ("中午", "正午") and hour < 12:
        return 12 if hour == 12 else hour
    return hour


def normalize_time(text: str) -> tuple[str, list[dict]]:
    """時間正規化

    將中文/混合時間表達轉為 `HH:MM` 格式。
    """
    if not text:
        return text, []
    changes: list[dict] = []
    result = text

    def _parse_num(s: str) -> int | None:
        """解析 hour/minute 字串（支援中文與阿拉伯）"""
        if s.isdigit():
            return int(s)
        return _parse_chn_number(s)

    def _time_full_replacer(m):
        period = m.group(1) or ""
        hour_str = m.group(2)
        minute_str = m.group(3)

        hour = _parse_num(hour_str)
        if hour is None or not (0 <= hour <= 23):
            return m.group(0)

        if minute_str == _TIME_MAP_HALF:
            minute = 30
        else:
            minute = _parse_num(minute_str)
            if minute is None or not (0 <= minute <= 59):
                return m.group(0)

        hour = _adjust_hour_by_period(hour, period)
        new = f"{hour:02d}:{minute:02d}"
        changes.append({
            "from": m.group(0).strip(),
            "to": new,
            "rule": "time_full",
        })
        return new

    def _time_hour_replacer(m):
        period = m.group(1) or ""
        hour_str = m.group(2)

        hour = _parse_num(hour_str)
        if hour is None or not (0 <= hour <= 23):
            return m.group(0)

        hour = _adjust_hour_by_period(hour, period)
        new = f"{hour:02d}:00"
        changes.append({
            "from": m.group(0).strip(),
            "to": new,
            "rule": "time_hour",
        })
        return new

    # 先跑 full（含分），再跑 hour only
    result = _TIME_PATTERN_FULL.sub(_time_full_replacer, result)
    result = _TIME_PATTERN_HOUR.sub(_time_hour_replacer, result)

    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 2. 站碼補零
# ══════════════════════════════════════════════════════════════════════
# 僅匹配 G/R 後接 1 位數字（需補零的 G0-G9、R0-R9）
# 排除已是 2 位數的 G10、R15 等
_STATION_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])([GgRr])(\d)(?![\da-z])"
)


def normalize_station_code(text: str) -> tuple[str, list[dict]]:
    """站碼補零：G7 → G07、R1 → R01"""
    if not text:
        return text, []
    changes: list[dict] = []

    def _replacer(m):
        prefix = m.group(1).upper()
        digit = m.group(2)
        new = f"{prefix}0{digit}"
        changes.append({
            "from": m.group(0),
            "to": new,
            "rule": "station_code_padding",
        })
        return new

    result = _STATION_CODE_PATTERN.sub(_replacer, text)
    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 3. 月台與數字空格正規化
# ══════════════════════════════════════════════════════════════════════
# 中文數字 + 月台 → 阿拉伯 + 空格 + 月台
_PLATFORM_CHN_PATTERN = re.compile(r"([一二三四五六七八九十])\s*月台")
# 阿拉伯 + 月台 → 阿拉伯 + 空格 + 月台
_PLATFORM_NUM_PATTERN = re.compile(r"(?<!\d)(\d{1,2})月台")


def normalize_platform(text: str) -> tuple[str, list[dict]]:
    """月台編號正規化：二月台 → 2 月台"""
    if not text:
        return text, []
    changes: list[dict] = []
    result = text

    def _chn_replacer(m):
        chn = m.group(1)
        num = _parse_chn_number(chn)
        if num is None or not (1 <= num <= 10):
            return m.group(0)
        new = f"{num} 月台"
        changes.append({
            "from": m.group(0),
            "to": new,
            "rule": "platform_chn",
        })
        return new

    def _num_replacer(m):
        num = m.group(1)
        new = f"{num} 月台"
        if new != m.group(0):
            changes.append({
                "from": m.group(0),
                "to": new,
                "rule": "platform_spacing",
            })
        return new

    result = _PLATFORM_CHN_PATTERN.sub(_chn_replacer, result)
    result = _PLATFORM_NUM_PATTERN.sub(_num_replacer, result)
    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 4. 時長/距離正規化
# ══════════════════════════════════════════════════════════════════════
_DURATION_UNITS = ["秒", "分鐘", "分", "小時", "分秒", "公尺", "米", "公里"]

_DURATION_PATTERN = re.compile(
    rf"([零一二兩三四五六七八九十]{{1,3}})({'|'.join(_DURATION_UNITS)})"
)


def normalize_duration(text: str) -> tuple[str, list[dict]]:
    """時長/距離中文數字 → 阿拉伯數字"""
    if not text:
        return text, []
    changes: list[dict] = []

    def _replacer(m):
        chn = m.group(1)
        unit = m.group(2)
        num = _parse_chn_number(chn)
        if num is None or num < 1 or num > 999:
            return m.group(0)
        new = f"{num} {unit}"
        changes.append({
            "from": m.group(0),
            "to": new,
            "rule": f"duration_{unit}",
        })
        return new

    result = _DURATION_PATTERN.sub(_replacer, text)
    return result, changes


# ══════════════════════════════════════════════════════════════════════
# 主函式：組合所有正規化
# ══════════════════════════════════════════════════════════════════════
# 數字/中文邊界補空格：時間、站碼等 正規化後若緊貼中文，補空格
_BOUNDARY_NUM_CHN = re.compile(r"(\d(?::\d+)?)([\u4e00-\u9fff])")
_BOUNDARY_CHN_NUM = re.compile(r"([\u4e00-\u9fff])(\d(?::\d+)?)")


def _apply_boundary_spacing(text: str) -> str:
    """在數字/時間與中文之間補空格（避免視覺黏連）"""
    # 時間 HH:MM 後若緊接非空白，強制補空格（解決 14:302 月台 這類黏連）
    text = re.sub(r"(\d{1,2}:\d{2})(?=\S)", r"\1 ", text)
    # 一般數字/中文邊界
    text = _BOUNDARY_NUM_CHN.sub(r"\1 \2", text)
    text = _BOUNDARY_CHN_NUM.sub(r"\1 \2", text)
    # 收斂多重空格
    text = re.sub(r" {2,}", " ", text)
    return text


def normalize_numbers(
    text: str,
    enable_time: bool = True,
    enable_station_code: bool = True,
    enable_platform: bool = True,
    enable_duration: bool = True,
    enable_spacing: bool = True,
) -> tuple[str, list[dict]]:
    """執行完整數字正規化 pipeline

    Returns:
        (最終文字, 所有階段的修正紀錄)
    """
    all_changes: list[dict] = []
    result = text or ""

    if enable_time:
        result, changes = normalize_time(result)
        all_changes.extend(changes)

    if enable_station_code:
        result, changes = normalize_station_code(result)
        all_changes.extend(changes)

    if enable_platform:
        result, changes = normalize_platform(result)
        all_changes.extend(changes)

    if enable_duration:
        result, changes = normalize_duration(result)
        all_changes.extend(changes)

    if enable_spacing:
        result = _apply_boundary_spacing(result)

    return result, all_changes


# ══════════════════════════════════════════════════════════════════════
# 內建測試
# ══════════════════════════════════════════════════════════════════════
TEST_CASES = [
    # (輸入, 預期輸出, 說明)
    # 時間
    ("十四時三十分", "14:30", "中文完整時間"),
    ("下午兩點半", "14:30", "下午+半"),
    ("早上九點十五分", "09:15", "上午+分鐘"),
    ("二十三時零五分", "23:05", "24小時制+零分"),
    ("上午七點整", "07:00", "整點"),
    ("中午十二點", "12:00", "中午"),

    # 站碼補零
    ("G7 站長回報", "G07 站長回報", "G7 → G07"),
    ("R1 月台", "R01 月台", "R1 → R01（月台獨立不受影響）"),
    ("G07 已是標準", "G07 已是標準", "已標準不動"),
    ("G12 也不動", "G12 也不動", "雙位數不動"),
    ("g5 小寫也要補零", "G05 小寫也要補零", "小寫轉大寫補零"),

    # 月台
    ("二月台列車", "2 月台列車", "二月台"),
    ("三月台門", "3 月台門", "三月台"),
    ("2月台", "2 月台", "阿拉伯補空格"),

    # 時長
    ("五分鐘", "5 分鐘", "分鐘"),
    ("十秒鐘", "10 秒鐘", "秒"),
    ("半小時後", "半小時後", "半不處理"),

    # 混合情境
    ("G7 站長，下午兩點半派員到二月台待命五分鐘",
     "G07 站長，14:30 派員到 2 月台待命 5 分鐘",
     "綜合測試"),

    # 保留不動的案例
    ("OCC 通告全線", "OCC 通告全線", "無數字"),
    ("25/26 車門", "25/26 車門", "車廂不動"),
]


def run_tests() -> int:
    print(f"🧪 執行 {len(TEST_CASES)} 個測試")
    print("=" * 70)
    passed = 0
    for i, (inp, expected, desc) in enumerate(TEST_CASES, 1):
        result, changes = normalize_numbers(inp)
        ok = result == expected
        mark = "✅" if ok else "❌"
        print(f"{mark} #{i:2} [{desc}]")
        print(f"     in:       {inp!r}")
        if not ok:
            print(f"     expected: {expected!r}")
            print(f"     actual:   {result!r}")
            if changes:
                print(f"     changes:  {changes}")
        else:
            passed += 1
    print()
    print("=" * 70)
    print(f"結果: {passed}/{len(TEST_CASES)} 通過")
    return 0 if passed == len(TEST_CASES) else 1


def main():
    p = argparse.ArgumentParser()
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--test", action="store_true", help="跑內建測試")
    grp.add_argument("--text", help="正規化單句")
    grp.add_argument("--file", help="正規化檔案內容")
    args = p.parse_args()

    if args.test:
        sys.exit(run_tests())

    text = args.text if args.text else Path(args.file).read_text(encoding="utf-8")
    result, changes = normalize_numbers(text)

    print("─── 原文 ───")
    print(text)
    print()
    print("─── 修正後 ───")
    print(result)
    print()
    print(f"─── 修正紀錄（{len(changes)} 處）───")
    for c in changes:
        print(f"  {c['from']!r} → {c['to']!r}  [{c['rule']}]")


if __name__ == "__main__":
    main()
