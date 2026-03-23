#!/usr/bin/env python3
"""
清洗官方文稿（去除章節標題、時間碼、說話者標籤），
僅保留實際說話的內容文字，再輸出供 CER 評測使用。

使用：
    python scripts/clean_reference.py \
        --input  experiments/reference/broadcast_20260317.txt \
        --output experiments/reference/broadcast_20260317_clean.txt
"""

import re
import argparse
from pathlib import Path


def clean_reference(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        # ── 移除章節標題 ─────────────────────────────────────────────
        # 例：「第 1 章節：開場」、「第2章節：...」
        if re.match(r'^第\s*\d+\s*章節', line):
            continue

        # ── 移除時間碼 ────────────────────────────────────────────────
        # 格式1：「0:044 秒XXX」→ 移除「0:044 秒」前綴
        # 格式2：「1:131 分鐘 13 秒XXX」→ 移除時間碼前綴
        line = re.sub(
            r'^\d+:\d+\s*(?:\d+\s*)?(?:秒|分鐘\s*\d+\s*秒)\s*',
            '', line
        )

        # ── 移除說話者標籤 ────────────────────────────────────────────
        # 例：「Delta呼叫Charlie」、「這裡是Charlie」（獨立行）
        # 僅移除行首的呼叫語，保留後面的實際內容
        line = re.sub(
            r'^(?:[A-Za-z]+(?:\s*呼叫\s*[A-Za-z]+)?\s+)?(?:這裡是\s*[A-Za-z]+\s*)?',
            '', line
        )

        # ── 移除括號注釋 ─────────────────────────────────────────────
        # 例：「太陽花（學運）」→「太陽花學運」、「（笑）」移除
        line = re.sub(r'（[^）]{0,5}）', '', line)   # 短括弧（補充說明）
        line = re.sub(r'\([^)]{0,5}\)', '', line)       # 英文括弧

        line = line.strip()
        if line:
            lines.append(line)

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    raw = args.input.read_text(encoding='utf-8')
    cleaned = clean_reference(raw)
    args.output.write_text(cleaned, encoding='utf-8')

    # 簡單統計
    raw_chars    = len(re.sub(r'[^\u4e00-\u9fff0-9a-zA-Z]', '', raw))
    clean_chars  = len(re.sub(r'[^\u4e00-\u9fff0-9a-zA-Z]', '', cleaned))
    removed_pct  = (raw_chars - clean_chars) / raw_chars * 100

    print(f'清洗完成')
    print(f'  原始字數：{raw_chars}')
    print(f'  清洗後  ：{clean_chars}')
    print(f'  移除    ：{raw_chars - clean_chars} 字（{removed_pct:.1f}%）')
    print(f'  輸出至  ：{args.output}')


if __name__ == '__main__':
    main()
