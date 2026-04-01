"""
aiSpeech Local（機密版）v2.0 - 雙引擎本地離線語音辨識系統
引擎 A：faster-whisper（Whisper large-v3 / medium / small）
引擎 B：FunASR SenseVoiceSmall（阿里達摩院）

適用於臺中捷運 OCC 機密通聯內容辨識
部署平台：Mac mini M4 24GB / MacBook Pro (Apple Silicon)
"""

import streamlit as st
import tempfile
import os
import json
import time
import subprocess
import wave
import io
import csv
import re
from datetime import datetime
from pathlib import Path
from enum import Enum

# ── 頁面設定 ──────────────────────────────────────────────
st.set_page_config(
    page_title="aiSpeech Local v2.0（機密版）",
    page_icon="🔒",
    layout="wide",
)

# ── 引擎定義 ──────────────────────────────────────────────

class Engine(str, Enum):
    FASTER_WHISPER = "faster-whisper"
    SENSEVOICE = "sensevoice"


ENGINE_INFO = {
    Engine.FASTER_WHISPER: {
        "label": "🅰 faster-whisper（OpenAI Whisper）",
        "description": "基於 CTranslate2 加速的 Whisper，適合需要最高準確度的場景",
        "models": {
            "large-v3": {"label": "Large-V3（最高準確度，較慢）", "size": "~3GB", "rtf_cpu": "~1.5x"},
            "medium": {"label": "Medium（平衡速度與準確度）", "size": "~1.5GB", "rtf_cpu": "~0.4x"},
            "small": {"label": "Small（快速）", "size": "~500MB", "rtf_cpu": "~0.15x"},
        },
    },
    Engine.SENSEVOICE: {
        "label": "🅱 SenseVoiceSmall（阿里 FunASR）",
        "description": "非自回歸架構，中文辨識優異，推論速度極快，含情緒辨識與事件偵測",
        "models": {
            "iic/SenseVoiceSmall": {
                "label": "SenseVoiceSmall（推薦，中文最佳）",
                "size": "~500MB",
                "rtf_cpu": "~0.1x",
            },
        },
    },
}


# ── 鐵道專有詞彙 ──────────────────────────────────────────

WHISPER_RAILWAY_PROMPT = (
    "臺中捷運行控中心通聯紀錄。"
    "北屯總站、高鐵臺中站、市政府站、文心森林公園站、大慶站、"
    "豐樂公園站、松竹站、四維國小站、文心中清站、"
    "CBTC、ZC、CLC、CBI、ATP、ATO、ATS、"
    "轉轍器、道岔、號誌機、閉塞區間、聯鎖、"
    "月台門、緊急停車按鈕、列車自動防護、列車自動運轉、"
    "行控中心、OCC、調度員、站務員、司機員、"
    "正線、副正線、橫渡線、袋型軌、駐車軌、"
    "供電、第三軌、牽引電力、APS、SCADA、"
    "收班、發班、夜間作業、試車、清車、巡軌"
)

SENSEVOICE_HOTWORDS = (
    "臺中捷運 行控中心 北屯總站 高鐵臺中站 市政府站 "
    "文心森林公園站 大慶站 豐樂公園站 松竹站 四維國小站 文心中清站 "
    "CBTC ZC CLC CBI ATP ATO ATS "
    "轉轍器 道岔 號誌機 閉塞區間 聯鎖 "
    "月台門 緊急停車按鈕 列車自動防護 列車自動運轉 "
    "OCC 調度員 站務員 司機員 "
    "正線 副正線 橫渡線 袋型軌 駐車軌 "
    "第三軌 牽引電力 APS SCADA "
    "收班 發班 夜間作業 試車 清車 巡軌"
)

CONFIG = {
    "target_sample_rate": 16000,
    "supported_formats": ["wav", "mp3", "ogg", "flac", "m4a", "raw"],
}

EMOTION_MAP = {
    "<|HAPPY|>": "😊 開心",
    "<|SAD|>": "😢 悲傷",
    "<|ANGRY|>": "😠 憤怒",
    "<|NEUTRAL|>": "😐 中性",
    "<|FEARFUL|>": "😨 恐懼",
    "<|DISGUSTED|>": "🤢 厭惡",
    "<|SURPRISED|>": "😲 驚訝",
}

EVENT_MAP = {
    "<|BGM|>": "🎵 背景音樂",
    "<|Speech|>": "🗣️ 語音",
    "<|Applause|>": "👏 掌聲",
    "<|Laughter|>": "😄 笑聲",
    "<|Cry|>": "😭 哭聲",
    "<|Sneeze|>": "🤧 噴嚏",
    "<|Breathe|>": "💨 呼吸",
    "<|Cough|>": "😷 咳嗽",
}


# ══════════════════════════════════════════════════════════
#  模型載入
# ══════════════════════════════════════════════════════════

@st.cache_resource
def load_faster_whisper(model_name: str):
    from faster_whisper import WhisperModel
    return WhisperModel(
        model_name, device="cpu", compute_type="int8",
        cpu_threads=os.cpu_count(),
    )


@st.cache_resource
def load_sensevoice(model_name: str):
    from funasr import AutoModel
    return AutoModel(
        model=model_name, trust_remote_code=True,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        device="cpu",
    )


def load_engine(engine: Engine, model_name: str):
    if engine == Engine.FASTER_WHISPER:
        return load_faster_whisper(model_name)
    else:
        return load_sensevoice(model_name)


# ══════════════════════════════════════════════════════════
#  音檔處理
# ══════════════════════════════════════════════════════════

def get_audio_info(file_path: str) -> dict:
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        info = json.loads(result.stdout)
        stream = info.get("streams", [{}])[0]
        return {
            "codec": stream.get("codec_name", "unknown"),
            "sample_rate": int(stream.get("sample_rate", 0)),
            "channels": int(stream.get("channels", 0)),
            "duration": float(info.get("format", {}).get("duration", 0)),
            "bit_depth": stream.get("bits_per_sample", "N/A"),
        }
    except Exception as e:
        return {"error": str(e)}


def convert_audio(input_path: str, output_path: str, target_sr: int = 16000) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-ar", str(target_sr), "-ac", "1",
            "-acodec", "pcm_s16le", "-f", "wav", output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except Exception:
        return False


def needs_audio_conversion(audio_info: dict) -> bool:
    return (
        audio_info.get("sample_rate", 0) != 16000
        or audio_info.get("channels", 0) != 1
        or audio_info.get("codec", "") not in ["pcm_s16le", "pcm_s16be"]
    )


# ══════════════════════════════════════════════════════════
#  辨識核心（雙引擎統一介面）
# ══════════════════════════════════════════════════════════

def transcribe_faster_whisper(model, audio_path: str, language: str,
                              use_vad: bool, vad_threshold: float,
                              custom_prompt: str = "") -> list:
    prompt = WHISPER_RAILWAY_PROMPT
    if custom_prompt:
        prompt += "、" + custom_prompt

    segments, info = model.transcribe(
        audio_path,
        language=language if language != "auto" else None,
        initial_prompt=prompt,
        beam_size=5,
        best_of=5,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        vad_filter=use_vad,
        vad_parameters=dict(
            threshold=vad_threshold,
            min_speech_duration_ms=300,
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    results = []
    for seg in segments:
        results.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "no_speech_prob": round(seg.no_speech_prob, 3),
            "emotion": None,
            "event": None,
            "engine": "faster-whisper",
        })
    return results


def parse_sensevoice_tags(raw_text: str) -> dict:
    emotion = None
    event = None
    text = raw_text

    for tag, label in EMOTION_MAP.items():
        if tag in text:
            emotion = label
            text = text.replace(tag, "")

    for tag, label in EVENT_MAP.items():
        if tag in text:
            event = label
            text = text.replace(tag, "")

    text = re.sub(r'<\|[^|]*\|>', '', text).strip()
    return {"text": text, "emotion": emotion, "event": event}


def transcribe_sensevoice(model, audio_path: str, language: str,
                          custom_hotwords: str = "") -> list:
    lang_map = {"zh": "zh", "en": "en", "ja": "ja", "yue": "yue",
                "ko": "ko", "auto": "auto"}
    sv_lang = lang_map.get(language, "auto")

    hotwords = SENSEVOICE_HOTWORDS
    if custom_hotwords:
        hotwords += " " + custom_hotwords.replace("、", " ")

    res = model.generate(
        input=audio_path,
        cache={},
        language=sv_lang,
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
        hotword=hotwords,
    )

    results = []
    if res and len(res) > 0:
        for item in res:
            raw_text = item.get("text", "")
            parsed = parse_sensevoice_tags(raw_text)

            timestamp = item.get("timestamp", [])
            if timestamp and len(timestamp) >= 2:
                start = timestamp[0][0] / 1000.0 if isinstance(timestamp[0], list) else 0
                end = timestamp[-1][-1] / 1000.0 if isinstance(timestamp[-1], list) else 0
            else:
                start = 0
                end = 0

            if parsed["text"]:
                results.append({
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "text": parsed["text"],
                    "no_speech_prob": 0,
                    "emotion": parsed["emotion"],
                    "event": parsed["event"],
                    "engine": "sensevoice",
                })
    return results


def transcribe(engine: Engine, model, audio_path: str, language: str,
               use_vad: bool = True, vad_threshold: float = 0.5,
               custom_vocab: str = "") -> list:
    if engine == Engine.FASTER_WHISPER:
        return transcribe_faster_whisper(
            model, audio_path, language, use_vad, vad_threshold, custom_vocab
        )
    else:
        return transcribe_sensevoice(model, audio_path, language, custom_vocab)


# ══════════════════════════════════════════════════════════
#  匯出功能
# ══════════════════════════════════════════════════════════

def fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_csv(results: list, include_extra: bool = False) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["開始時間", "結束時間", "辨識文字", "無語音機率"]
    if include_extra:
        headers += ["情緒", "事件", "辨識引擎"]
    writer.writerow(headers)
    for r in results:
        row = [fmt_ts(r["start"]), fmt_ts(r["end"]), r["text"], r["no_speech_prob"]]
        if include_extra:
            row += [r.get("emotion", ""), r.get("event", ""), r.get("engine", "")]
        writer.writerow(row)
    return output.getvalue()


def export_srt(results: list) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        lines += [str(i), f"{fmt_srt(r['start'])} --> {fmt_srt(r['end'])}", r["text"], ""]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  結果顯示
# ══════════════════════════════════════════════════════════

def render_results(results: list, audio_info: dict, elapsed: float,
                   engine: Engine):
    if not results:
        st.warning("未偵測到語音內容")
        return

    duration = audio_info.get("duration", 0)
    rtf = elapsed / duration if duration > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("辨識耗時", f"{elapsed:.1f} 秒")
    c2.metric("RTF", f"{rtf:.2f}x", help="< 1.0 表示比即時快")
    c3.metric("片段數", len(results))
    c4.metric("引擎", "Whisper" if engine == Engine.FASTER_WHISPER else "SenseVoice")

    st.subheader("辨識結果")
    full_text = "".join([r["text"] for r in results])
    st.text_area("全文", full_text, height=150)

    has_emotion = any(r.get("emotion") for r in results)
    has_event = any(r.get("event") and r["event"] != "🗣️ 語音" for r in results)

    with st.expander("逐段詳細結果", expanded=True):
        for r in results:
            conf = "🟢" if r["no_speech_prob"] < 0.3 else (
                "🟡" if r["no_speech_prob"] < 0.6 else "🔴"
            )
            line = f"{conf} **[{fmt_ts(r['start'])} → {fmt_ts(r['end'])}]** {r['text']}"
            if r.get("emotion"):
                line += f"　{r['emotion']}"
            if r.get("event") and r["event"] != "🗣️ 語音":
                line += f"　{r['event']}"
            st.markdown(line)

    # SenseVoice 情緒統計
    if has_emotion:
        st.subheader("情緒分析摘要")
        emo_counts = {}
        for r in results:
            e = r.get("emotion")
            if e:
                emo_counts[e] = emo_counts.get(e, 0) + 1
        if emo_counts:
            cols = st.columns(min(len(emo_counts), 6))
            for i, (emo, cnt) in enumerate(sorted(emo_counts.items(), key=lambda x: -x[1])):
                cols[i % len(cols)].metric(emo, f"{cnt} 段")

    # SenseVoice 事件偵測
    if has_event:
        st.subheader("音訊事件偵測")
        evts = [r["event"] for r in results if r.get("event") and r["event"] != "🗣️ 語音"]
        evt_counts = {}
        for ev in evts:
            evt_counts[ev] = evt_counts.get(ev, 0) + 1
        for ev, cnt in sorted(evt_counts.items(), key=lambda x: -x[1]):
            st.markdown(f"- {ev}：{cnt} 次")

    # 匯出
    st.subheader("匯出結果")
    extra = engine == Engine.SENSEVOICE
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    c1, c2, c3 = st.columns(3)
    c1.download_button("📄 CSV", export_csv(results, extra),
                       f"transcript_{ts}.csv", mime="text/csv")
    c2.download_button("🎬 SRT", export_srt(results),
                       f"transcript_{ts}.srt", mime="text/plain")
    c3.download_button("📋 JSON", json.dumps(results, ensure_ascii=False, indent=2),
                       f"transcript_{ts}.json", mime="application/json")


# ══════════════════════════════════════════════════════════
#  主介面
# ══════════════════════════════════════════════════════════

st.title("🔒 aiSpeech Local v2.0（機密版）")
st.caption("雙引擎本地離線語音辨識系統 — 所有資料不離開本機")

# ── 側邊欄 ────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 引擎與模型")

    selected_engine = st.radio(
        "辨識引擎",
        options=[Engine.SENSEVOICE, Engine.FASTER_WHISPER],
        format_func=lambda x: ENGINE_INFO[x]["label"],
        index=0,
    )
    st.caption(ENGINE_INFO[selected_engine]["description"])

    available_models = ENGINE_INFO[selected_engine]["models"]
    selected_model = st.selectbox(
        "模型",
        options=list(available_models.keys()),
        format_func=lambda x: available_models[x]["label"],
    )
    mi = available_models[selected_model]
    st.caption(f"大小：{mi['size']}　|　CPU RTF：{mi['rtf_cpu']}")

    st.divider()

    if selected_engine == Engine.FASTER_WHISPER:
        lang_opts = ["zh", "ja", "en", "auto"]
        lang_lbl = {"zh": "中文", "ja": "日文", "en": "英文", "auto": "自動偵測"}
    else:
        lang_opts = ["zh", "en", "ja", "yue", "ko", "auto"]
        lang_lbl = {"zh": "中文", "en": "英文", "ja": "日文",
                    "yue": "粵語", "ko": "韓文", "auto": "自動偵測"}

    language = st.selectbox("辨識語言", options=lang_opts,
                            format_func=lambda x: lang_lbl[x], index=0)

    if selected_engine == Engine.FASTER_WHISPER:
        st.divider()
        use_vad = st.toggle("啟用 VAD", value=True)
        vad_threshold = st.slider("VAD 閾值", 0.1, 0.9, 0.5, 0.1) if use_vad else 0.5
    else:
        use_vad, vad_threshold = True, 0.5
        st.info("💡 SenseVoice 已內建 fsmn-vad")

    st.divider()
    st.header("📋 自訂詞彙")
    custom_vocab = st.text_area("附加專有名詞（空格或頓號分隔）",
                                placeholder="新站名A 新術語B", height=80)

    st.divider()
    st.header("ℹ️ 系統狀態")
    st.info(f"CPU 核心數：{os.cpu_count()}")
    ffmpeg_ok = subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0
    st.success("ffmpeg：✅") if ffmpeg_ok else st.error("ffmpeg：❌ brew install ffmpeg")


# ── 功能分頁 ──────────────────────────────────────────────

tab_file, tab_rt, tab_batch, tab_cmp = st.tabs([
    "📁 檔案辨識", "🎙️ 近即時辨識", "📦 批次處理", "⚖️ 雙引擎比較"
])

# ═══ Tab 1：檔案辨識 ══════════════════════════════════════
with tab_file:
    uploaded = st.file_uploader("上傳音檔", type=CONFIG["supported_formats"],
                                key="up_file")
    if uploaded:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{uploaded.name.split('.')[-1]}"
        ) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        ainfo = get_audio_info(tmp_path)
        if "error" not in ainfo:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("編碼", ainfo["codec"])
            c2.metric("取樣率", f"{ainfo['sample_rate']} Hz")
            c3.metric("聲道", ainfo["channels"])
            c4.metric("長度", fmt_ts(ainfo["duration"]))

            need_conv = needs_audio_conversion(ainfo)
            if need_conv:
                st.info("⚡ 將自動轉換為 16kHz Mono WAV")

        if st.button("🚀 開始辨識", type="primary", use_container_width=True, key="b1"):
            with st.spinner("載入模型..."):
                mdl = load_engine(selected_engine, selected_model)

            conv_path = tmp_path
            if need_conv:
                with st.spinner("轉換音檔..."):
                    conv_path = tmp_path + "_16k.wav"
                    if not convert_audio(tmp_path, conv_path):
                        st.error("轉換失敗"); st.stop()

            with st.spinner("辨識中..."):
                t0 = time.time()
                res = transcribe(selected_engine, mdl, conv_path, language,
                                 use_vad, vad_threshold, custom_vocab)
                elapsed = time.time() - t0

            render_results(res, ainfo, elapsed, selected_engine)


# ═══ Tab 2：近即時辨識 ════════════════════════════════════
with tab_rt:
    st.info(
        "🎙️ 錄音軟體將音檔輸出到監控資料夾，系統自動偵測新檔並辨識。\n\n"
        "💡 SenseVoice 引擎速度更快，推薦用於近即時場景。"
    )
    watch_dir = st.text_input("監控資料夾",
                              value=str(Path.home() / "aiSpeech_incoming"), key="wd")
    poll_sec = st.slider("檢查間隔（秒）", 1, 10, 3, key="poll")

    if st.button("▶️ 開始監控", type="primary", key="b2"):
        wp = Path(watch_dir)
        wp.mkdir(parents=True, exist_ok=True)
        with st.spinner("載入模型..."):
            mdl = load_engine(selected_engine, selected_model)

        processed = set()
        status = st.empty()
        area = st.container()
        status.success(f"✅ 監控中：{watch_dir}（{selected_engine.value}）")

        while True:
            for f in sorted(wp.glob("*")):
                if (f.suffix.lower().lstrip('.') in CONFIG["supported_formats"]
                        and str(f) not in processed and f.stat().st_size > 0):
                    processed.add(str(f))
                    with area:
                        st.markdown(f"---\n**📄 {f.name}**")
                        conv = str(f) + "_16k.wav"
                        convert_audio(str(f), conv)
                        t0 = time.time()
                        res = transcribe(selected_engine, mdl, conv, language,
                                         use_vad, vad_threshold, custom_vocab)
                        el = time.time() - t0
                        for s in res:
                            line = f"**[{fmt_ts(s['start'])}→{fmt_ts(s['end'])}]** {s['text']}"
                            if s.get("emotion"): line += f"　{s['emotion']}"
                            st.markdown(line)
                        st.caption(f"⏱ {el:.1f}s")
                        if os.path.exists(conv): os.remove(conv)
            time.sleep(poll_sec)


# ═══ Tab 3：批次處理 ══════════════════════════════════════
with tab_batch:
    bdir = st.text_input("音檔資料夾", value="", placeholder="/path/to/audio", key="bd")

    if bdir and st.button("🚀 批次辨識", type="primary", key="b3"):
        bp = Path(bdir)
        if not bp.exists():
            st.error(f"路徑不存在：{bdir}"); st.stop()

        files = []
        for ext in CONFIG["supported_formats"]:
            files.extend(bp.glob(f"*.{ext}"))
            files.extend(bp.glob(f"*.{ext.upper()}"))
        files = sorted(set(files))

        if not files:
            st.warning("沒有找到音檔"); st.stop()

        st.info(f"找到 {len(files)} 個音檔（{selected_engine.value}）")
        mdl = load_engine(selected_engine, selected_model)
        all_res = {}
        total_t = 0
        prog = st.progress(0)

        for i, f in enumerate(files):
            st.caption(f"處理：{f.name}")
            conv = str(f) + "_16k.wav"
            convert_audio(str(f), conv)
            t0 = time.time()
            res = transcribe(selected_engine, mdl, conv, language,
                             use_vad, vad_threshold, custom_vocab)
            total_t += time.time() - t0
            all_res[f.name] = res
            prog.progress((i + 1) / len(files))
            if os.path.exists(conv): os.remove(conv)

        st.success(f"✅ {len(files)} 檔完成，總耗時 {total_t:.1f}s")

        extra = selected_engine == Engine.SENSEVOICE
        buf = io.StringIO()
        w = csv.writer(buf)
        hdr = ["檔案", "開始", "結束", "文字", "無語音機率"]
        if extra: hdr += ["情緒", "事件"]
        w.writerow(hdr)
        for fn, segs in all_res.items():
            for r in segs:
                row = [fn, fmt_ts(r["start"]), fmt_ts(r["end"]), r["text"], r["no_speech_prob"]]
                if extra: row += [r.get("emotion", ""), r.get("event", "")]
                w.writerow(row)

        st.download_button("📄 下載全部 CSV", buf.getvalue(),
                           f"batch_{datetime.now():%Y%m%d_%H%M%S}.csv",
                           mime="text/csv", use_container_width=True)


# ═══ Tab 4：雙引擎比較 ════════════════════════════════════
with tab_cmp:
    st.markdown(
        "### ⚖️ 雙引擎同步比較\n"
        "上傳同一段音檔，同時用兩個引擎辨識，比較準確度與速度。"
    )

    cmp_file = st.file_uploader("上傳音檔", type=CONFIG["supported_formats"], key="up_cmp")

    ca, cb = st.columns(2)
    with ca:
        st.markdown("**🅰 faster-whisper**")
        fw_mdl_name = st.selectbox(
            "模型", list(ENGINE_INFO[Engine.FASTER_WHISPER]["models"].keys()),
            format_func=lambda x: ENGINE_INFO[Engine.FASTER_WHISPER]["models"][x]["label"],
            key="cmp_fw")
    with cb:
        st.markdown("**🅱 SenseVoiceSmall**")
        st.caption("固定使用 SenseVoiceSmall")

    if cmp_file and st.button("🔄 同步辨識", type="primary",
                               use_container_width=True, key="b4"):
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{cmp_file.name.split('.')[-1]}"
        ) as tmp:
            tmp.write(cmp_file.read())
            cpath = tmp.name

        ainfo = get_audio_info(cpath)
        conv = cpath + "_16k.wav"
        with st.spinner("轉換..."):
            convert_audio(cpath, conv)

        # 引擎 A
        with st.spinner("faster-whisper 載入 + 辨識..."):
            fw = load_faster_whisper(fw_mdl_name)
            t0 = time.time()
            fw_res = transcribe_faster_whisper(fw, conv, language, True, 0.5, custom_vocab)
            fw_t = time.time() - t0

        # 引擎 B
        with st.spinner("SenseVoiceSmall 載入 + 辨識..."):
            sv = load_sensevoice("iic/SenseVoiceSmall")
            t0 = time.time()
            sv_res = transcribe_sensevoice(sv, conv, language, custom_vocab)
            sv_t = time.time() - t0

        dur = ainfo.get("duration", 1)
        st.divider()

        la, lb = st.columns(2)
        with la:
            st.markdown("### 🅰 faster-whisper")
            st.metric("耗時", f"{fw_t:.1f}s")
            st.metric("RTF", f"{fw_t/dur:.2f}x")
            st.text_area("全文", "".join(r["text"] for r in fw_res), height=200, key="fw_t")
            with st.expander("逐段"):
                for r in fw_res:
                    st.markdown(f"**[{fmt_ts(r['start'])}→{fmt_ts(r['end'])}]** {r['text']}")

        with lb:
            st.markdown("### 🅱 SenseVoiceSmall")
            st.metric("耗時", f"{sv_t:.1f}s")
            st.metric("RTF", f"{sv_t/dur:.2f}x")
            st.text_area("全文", "".join(r["text"] for r in sv_res), height=200, key="sv_t")
            with st.expander("逐段（含情緒/事件）"):
                for r in sv_res:
                    line = f"**[{fmt_ts(r['start'])}→{fmt_ts(r['end'])}]** {r['text']}"
                    if r.get("emotion"): line += f"　{r['emotion']}"
                    if r.get("event") and r["event"] != "🗣️ 語音": line += f"　{r['event']}"
                    st.markdown(line)

        st.divider()
        if sv_t > 0 and fw_t > 0:
            ratio = fw_t / sv_t
            if ratio > 1:
                st.success(f"⚡ SenseVoice 比 faster-whisper 快 **{ratio:.1f}** 倍")
            else:
                st.info(f"faster-whisper 比 SenseVoice 快 **{1/ratio:.1f}** 倍")

        if os.path.exists(conv): os.remove(conv)


# ── Footer ────────────────────────────────────────────────
st.divider()
st.caption(
    "🔒 aiSpeech Local v2.0 | 雙引擎：faster-whisper + SenseVoiceSmall | "
    "所有資料本機處理 | 臺中捷運 OCC"
)
