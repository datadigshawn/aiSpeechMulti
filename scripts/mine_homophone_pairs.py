"""挖掘同音錯→正 / 對齊念稿 GT 分析選字錯（兩種模式）。

mode=candidate（DB 候選，已實證為死路，保留供對照）：
    把 general 同音校正器當候選產生器跑過 shipped transcript、按頻率聚合。
    結論：無 GT → 高頻全是誤報（是→時…），DB 挖不出 curated 詞典。詳見
    _decisions/2026-06-22 選字問題策略。

mode=align（念稿 GT 對齊，主用）：
    吃「念稿 ASR 輸出 ↔ 已知正解(GT)」配對，字元對齊後抽出：
      ① 配對錯例：(ASR錯字 → GT正字) 混淆對 + 同音/近音分類 + 頻率 + context
      ② fine-tune manifest：audio ↔ GT 文字（餵既有 build_finetune_dataset.py）
      ③ 量測摘要：CER、替換中「同音(音對字錯)」占比 = 選字錯比例、選字準確率
    這是「念稿→3090 聲學 fine-tune」流程的分析入口；針對席位間安靜對話的
    語境相依選字錯（是/時、做/作）找出真實 pattern，並把配對音檔導向 fine-tune。

用法：
    # 念稿做完，把 ASR 與 GT 配成 jsonl（{"asr","gt","audio"?,"id"?}）或 tsv
    python scripts/mine_homophone_pairs.py align --pairs pairs.jsonl
    # 或目錄對應（同檔名 stem 配對）
    python scripts/mine_homophone_pairs.py align --asr-dir asr/ --gt-dir gt/ --audio-dir wav/

    # 舊的 DB 候選模式（對照用）
    python scripts/mine_homophone_pairs.py candidate --sample 1500
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_LM_PKL = PROJECT_ROOT / "experiments" / "ngram_lm" / "char_4gram.pkl"
_TERMS_TXT = PROJECT_ROOT / "experiments" / "lm_corpus" / "glossary" / "domain_terms_zh.txt"
_GLOSSARY = PROJECT_ROOT / "experiments" / "lm_corpus" / "glossary"
_ALIGN_OUT = PROJECT_ROOT / "experiments" / "lm_corpus" / "align_out"

_CJK = re.compile(r"[一-鿿]")
# 對齊前正規化：去掉空白與標點（純選字錯分析，不被標點差異污染）；保留 CJK/英數
_DROP = re.compile(r"[\s。，、！？!?,.；;：:「」『』（）()【】\[\]\"'…—\-~·／/]+")


def _has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ""))


def _norm_for_align(s: str) -> str:
    return _DROP.sub("", s or "")


# ── 拼音工具（兩模式共用）─────────────────────────────────
def _pinyin_tools():
    from scripts.homophone_corrector import _toneless, _lev  # noqa
    return _toneless, _lev


def _classify(a: str, b: str, toneless, lev) -> str:
    pa, pb = toneless(a), toneless(b)
    if not pa or not pb:
        return "異音"
    if pa == pb:
        return "同音"
    d = lev(pa, pb)
    return f"近音(d={d})" if d <= 2 else "異音"


# ════════════════════════════════════════════════════════════
# mode=candidate（DB 候選；對照用）
# ════════════════════════════════════════════════════════════
def run_candidate(db_path: Path, sample: int, max_len: int) -> None:
    from scripts.homophone_corrector import HomophoneCorrector
    toneless, lev = _pinyin_tools()
    hc = HomophoneCorrector.from_pickle(
        _LM_PKL,
        terms_path=_TERMS_TXT if _TERMS_TXT.exists() else None,
        general_correction=True,
    )
    if hc is None:
        print("校正器不可用（缺 pypinyin 或 .pkl）"); return

    con = sqlite3.connect(str(db_path))
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT transcript FROM transcripts WHERE transcript IS NOT NULL")]
    con.close()
    texts = sorted({s for s in rows if s and _has_cjk(s) and 2 <= len(s) <= max_len})[:sample]

    pair_count: Counter = Counter()
    pair_ctx: dict = defaultdict(list)
    n_changed = 0
    for s in texts:
        _, changes = hc.correct(s)
        if not changes:
            continue
        n_changed += 1
        for ch in changes:
            i = ch["pos"]; w, r = ch["from"], ch["to"]
            pair_count[(w, r)] += 1
            if len(pair_ctx[(w, r)]) < 3:
                pair_ctx[(w, r)].append(s[max(0, i - 2):i] + "[" + w + "]" + s[i + 1:i + 3])

    out = _GLOSSARY / "homophone_candidates.tsv"
    lines = ["次數\t錯\t正\t類型\t範例"]
    for (w, r), c in pair_count.most_common():
        lines.append(f"{c}\t{w}\t{r}\t{_classify(w, r, toneless, lev)}\t{' / '.join(pair_ctx[(w, r)])}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"掃描 transcript={len(texts)}　有提案={n_changed}　unique(錯→正)={len(pair_count)}")
    print(f"輸出：{out}")
    print("（提醒：此模式無 GT，高頻多為誤報，不可直接入詞典——僅對照用）")


# ════════════════════════════════════════════════════════════
# mode=align（念稿 GT 對齊；主用）
# ════════════════════════════════════════════════════════════
def _load_pairs(args) -> list[dict]:
    """回傳 [{"id","asr","gt","audio"?}]。支援 --pairs(jsonl/tsv) 或 --asr-dir/--gt-dir。"""
    pairs: list[dict] = []
    if args.pairs:
        p = Path(args.pairs)
        if p.suffix == ".jsonl":
            for ln in p.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                d = json.loads(ln)
                asr = d.get("asr") or d.get("hyp") or d.get("pred") or ""
                gt = d.get("gt") or d.get("ref") or d.get("target") or ""
                if asr and gt:
                    pairs.append({"id": str(d.get("id") or len(pairs)),
                                  "asr": asr, "gt": gt, "audio": d.get("audio")})
        else:  # tsv: asr <TAB> gt [<TAB> audio]
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
                cols = ln.rstrip("\n").split("\t")
                if len(cols) < 2:
                    continue
                if i == 0 and ("asr" in cols[0].lower() or "gt" in cols[1].lower()):
                    continue  # header
                pairs.append({"id": str(i), "asr": cols[0], "gt": cols[1],
                              "audio": cols[2] if len(cols) > 2 else None})
    elif args.asr_dir and args.gt_dir:
        asr_dir, gt_dir = Path(args.asr_dir), Path(args.gt_dir)
        audio_dir = Path(args.audio_dir) if args.audio_dir else None
        gts = {f.stem: f for f in gt_dir.glob("*.txt")}
        for stem, gf in sorted(gts.items()):
            af = asr_dir / f"{stem}.txt"
            if not af.exists():
                continue
            audio = None
            if audio_dir:
                for ext in (".wav", ".m4a", ".mp3", ".flac"):
                    cand = audio_dir / f"{stem}{ext}"
                    if cand.exists():
                        audio = str(cand); break
            pairs.append({"id": stem,
                          "asr": af.read_text(encoding="utf-8").strip(),
                          "gt": gf.read_text(encoding="utf-8").strip(),
                          "audio": audio})
    return pairs


def _align_one(asr: str, gt: str):
    """字元對齊 → (subs, M, S, D, I)。subs=[(asr字, gt字, gt位置)]。"""
    a, b = _norm_for_align(asr), _norm_for_align(gt)
    subs = []
    M = S = D = I = 0
    for tag, a1, a2, b1, b2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        la, lb = a2 - a1, b2 - b1
        if tag == "equal":
            M += la
        elif tag == "replace":
            s = min(la, lb); S += s
            if la > lb:
                I += la - lb
            elif lb > la:
                D += lb - la
            for k in range(s):
                subs.append((a[a1 + k], b[b1 + k], b1 + k))
        elif tag == "delete":      # ASR 多出的字 → 插入
            I += la
        elif tag == "insert":      # GT 有、ASR 漏 → 刪除
            D += lb
    return subs, b, M, S, D, I


def run_align(args) -> None:
    toneless, lev = _pinyin_tools()
    pairs = _load_pairs(args)
    if not pairs:
        print("沒讀到配對。請給 --pairs <jsonl/tsv> 或 --asr-dir/--gt-dir。"); return

    conf_count: Counter = Counter()      # (asr錯, gt正) -> 次數
    conf_ctx: dict = defaultdict(list)
    tot_M = tot_S = tot_D = tot_I = tot_ref = 0
    homo_S = 0                            # 替換中「同音」數（音對字錯 = 選字錯）
    manifest = []                         # fine-tune 樣本（有 audio 才收）

    for pr in pairs:
        subs, gt_norm, M, S, D, I = _align_one(pr["asr"], pr["gt"])
        tot_M += M; tot_S += S; tot_D += D; tot_I += I; tot_ref += len(gt_norm)
        for a_ch, g_ch, gi in subs:
            cls = _classify(a_ch, g_ch, toneless, lev)
            if cls == "同音":
                homo_S += 1
            conf_count[(a_ch, g_ch)] += 1
            if len(conf_ctx[(a_ch, g_ch)]) < 3:
                conf_ctx[(a_ch, g_ch)].append(
                    gt_norm[max(0, gi - 2):gi] + "[" + a_ch + "→" + g_ch + "]" + gt_norm[gi + 1:gi + 3])
        if pr.get("audio"):
            manifest.append({"audio": pr["audio"], "text": pr["gt"], "id": pr["id"]})

    _ALIGN_OUT.mkdir(parents=True, exist_ok=True)

    # ① 配對錯例 TSV（同音優先，再依頻率）
    conf_tsv = _ALIGN_OUT / "confusion_pairs.tsv"
    def _sortkey(item):
        (a, g), c = item
        cls = _classify(a, g, toneless, lev)
        return (0 if cls == "同音" else 1 if cls.startswith("近音") else 2, -c)
    lines = ["次數\t錯(ASR)\t正(GT)\t類型\t範例"]
    for (a, g), c in sorted(conf_count.items(), key=_sortkey):
        lines.append(f"{c}\t{a}\t{g}\t{_classify(a, g, toneless, lev)}\t{' / '.join(conf_ctx[(a, g)])}")
    conf_tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ② fine-tune manifest（audio↔GT；餵 build_finetune_dataset.py）
    if manifest:
        mf = _ALIGN_OUT / "finetune_manifest.jsonl"
        with open(mf, "w", encoding="utf-8") as f:
            for r in manifest:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ③ 量測摘要
    cer = (tot_S + tot_D + tot_I) / max(1, tot_ref)
    # 選字準確率 = 對 / (對 + 同音替換)：音抓到的位置(M=音字皆對, 同音=音對字錯)中選對字比例。
    # 異音替換屬真誤聽(非選字機會)，不計入分母。
    sel_acc = tot_M / max(1, tot_M + homo_S)
    homo_ratio = homo_S / max(1, tot_S)
    print(f"配對={len(pairs)}　GT字數={tot_ref}　配對音檔={len(manifest)}")
    print(f"對齊：對={tot_M} 替換S={tot_S} 漏D={tot_D} 多I={tot_I}")
    print(f"CER≈{cer:.4f}（(S+D+I)/GT字數）")
    print(f"替換中『同音(音對字錯=選字錯)』={homo_S}　占替換 {homo_ratio*100:.1f}%")
    print(f"選字準確率≈{sel_acc*100:.2f}%　（對/(對+同音替換)；音抓到位置選對字比例）")
    print(f"輸出：{conf_tsv}")
    if manifest:
        print(f"　　　{_ALIGN_OUT / 'finetune_manifest.jsonl'}（餵 build_finetune_dataset.py）")
    print("\n=== top 20 選字錯（同音優先）===")
    print("\n".join(lines[:21]))


def main() -> None:
    ap = argparse.ArgumentParser(description="同音錯→正 挖掘 / 念稿 GT 對齊分析")
    sub = ap.add_subparsers(dest="mode", required=True)

    pc = sub.add_parser("candidate", help="DB 候選（對照用，無 GT）")
    pc.add_argument("--db", default=str(PROJECT_ROOT / "data" / "aiSpeechMulti.db"))
    pc.add_argument("--sample", type=int, default=1500)
    pc.add_argument("--max-len", type=int, default=30)

    pa = sub.add_parser("align", help="念稿 ASR↔GT 對齊（主用）")
    pa.add_argument("--pairs", help="jsonl({asr,gt,audio?}) 或 tsv(asr<TAB>gt[<TAB>audio])")
    pa.add_argument("--asr-dir", help="ASR 文字目錄（*.txt，stem 配對）")
    pa.add_argument("--gt-dir", help="GT 正解目錄（*.txt，stem 配對）")
    pa.add_argument("--audio-dir", help="音檔目錄（選填，stem 配對；給 fine-tune manifest）")

    args = ap.parse_args()
    if args.mode == "candidate":
        run_candidate(Path(args.db), args.sample, args.max_len)
    else:
        run_align(args)


if __name__ == "__main__":
    main()