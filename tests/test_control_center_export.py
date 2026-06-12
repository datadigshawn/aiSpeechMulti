from __future__ import annotations

import zipfile
from datetime import datetime

from utils.control_center_export import (
    collect_control_center_rows,
    export_control_center_docx,
    export_control_center_from_records,
    parse_filename_datetime,
    title_date_from_results,
)


def test_parse_filename_datetime_supports_tmrt_short_date_names():
    dt = parse_filename_datetime("260603_北屯機廠號誌故障_正線_072318")

    assert dt == datetime(2026, 6, 3, 7, 23, 18)


def test_parse_filename_datetime_supports_full_date_time_names():
    assert parse_filename_datetime("radio_20251201_140000") == datetime(2025, 12, 1, 14, 0, 0)
    assert parse_filename_datetime("rec_20251201140509") == datetime(2025, 12, 1, 14, 5, 9)


def test_collect_control_center_rows_localizes_sentence_times():
    rows = collect_control_center_rows(
        [
            {
                "filename": "260603_北屯機廠號誌故障_正線_072318.wav",
                "status": "success",
                "transcript": "第一句。第二句。",
                "duration_sec": 20,
            }
        ]
    )

    assert [(row.time, row.text, row.speaker, row.note) for row in rows] == [
        ("07:23:18", "第一句。", "", ""),
        ("07:23:28", "第二句。", "", ""),
    ]


def test_export_control_center_docx_writes_word_table(tmp_path):
    results = [
        {
            "filename": "260603_北屯機廠號誌故障_正線_072318.wav",
            "status": "success",
            "transcript": "OCC通告全線。",
            "duration_sec": 8,
        }
    ]

    out = export_control_center_docx(
        all_results=results,
        filename_datetimes={},
        output_dir=tmp_path,
        timestamp="20260610_103639",
        event_name="OP1",
    )

    assert out.name == "OP1_行控中心格式_20260603_20260610_103639.docx"
    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")

    assert title_date_from_results(results, {}) == "20260603"
    assert "時間" in document_xml
    assert "發話者" in document_xml
    assert "通聯內容" in document_xml
    assert "備註" in document_xml
    assert "07:23:18" in document_xml
    assert "OCC通告全線。" in document_xml


def test_export_from_records_txt_converts_utc_and_sorts(tmp_path):
    # 即時辨識：DB transcript 紀錄（created_at 為 SQLite CURRENT_TIMESTAMP = UTC），
    # 一句一列；輸出依時間升冪、發話者/備註留空、UTC→本地（測試時固定 +0 以免依賴時區）。
    records = [
        {"transcript": "後到的句子。", "created_at": "2026-06-03 02:28:40"},
        {"transcript": "先到的句子。", "created_at": "2026-06-03 02:27:59"},
        {"transcript": "", "created_at": "2026-06-03 02:27:50"},  # 空白略過
    ]

    out = export_control_center_from_records(
        records,
        tmp_path,
        timestamp="20260612_101010",
        event_name="號誌異常",
        fmt="txt",
        utc_to_local=False,
    )

    assert out.name == "號誌異常_行控中心格式_20260603_20260612_101010.txt"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "20260603"
    assert lines[3] == "時間\t發話者\t通聯內容\t備註"
    # 升冪排序 + 留空欄位 + 空白句略過
    assert lines[4:] == [
        "02:27:59\t\t先到的句子。\t",
        "02:28:40\t\t後到的句子。\t",
    ]
