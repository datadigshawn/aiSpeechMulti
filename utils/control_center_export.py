"""Control-center transcript export helpers.

Produces the operations-control-center table format used by the lab batch ASR
flow.  The DOCX writer intentionally uses only the Python standard library so
the export works in existing deployments without an extra runtime dependency.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from utils.sentence_localizer import localize_sentences


@dataclass(frozen=True)
class ControlCenterRow:
    time: str
    text: str
    speaker: str = ""
    note: str = ""


def parse_filename_datetime(stem: str) -> datetime | None:
    """Parse common audio filename date/time patterns.

    Supported examples:
    - ``radio_20251201_140000``
    - ``20251201140000``
    - ``260603_北屯機廠號誌故障_正線_072318`` (ROC-style short year here means
      AD 2026, not Minguo year)
    """
    patterns = [
        r"(20\d{2})(\d{2})(\d{2})[_\- ]?(\d{2})(\d{2})(\d{2})",
        r"(20\d{2})(\d{2})(\d{2}).*?(\d{2})(\d{2})(\d{2})(?!\d)",
        r"(?<!\d)(\d{2})(\d{2})(\d{2}).*?(\d{2})(\d{2})(\d{2})(?!\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, stem)
        if not match:
            continue
        year = int(match.group(1))
        if year < 100:
            year += 2000
        try:
            return datetime(
                year,
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                int(match.group(6)),
            )
        except ValueError:
            continue
    return None


def collect_control_center_rows(
    all_results: list[dict],
    filename_datetimes: dict[str, datetime] | None = None,
) -> list[ControlCenterRow]:
    """Turn ASR result entries into time/text rows for the control-center table."""
    filename_datetimes = filename_datetimes or {}

    def _sort_key(result: dict) -> datetime:
        stem = Path(result.get("filename", "")).stem
        return filename_datetimes.get(stem) or parse_filename_datetime(stem) or datetime.max

    rows: list[ControlCenterRow] = []
    for result in sorted(all_results, key=_sort_key):
        if result.get("status") != "success":
            continue
        transcript = (result.get("transcript") or "").strip()
        if not transcript:
            continue

        stem = Path(result.get("filename", "")).stem
        start_dt = filename_datetimes.get(stem) or parse_filename_datetime(stem)
        localized = localize_sentences(
            segments=result.get("segments"),
            session_start=start_dt,
            transcript=transcript,
            audio_duration_sec=result.get("duration_sec"),
        )

        if not localized:
            time_label = start_dt.strftime("%H:%M:%S") if start_dt else ""
            rows.append(ControlCenterRow(time=time_label, text=transcript))
            continue

        for item in localized:
            abs_time = item.get("abs_time")
            if abs_time:
                try:
                    time_label = datetime.fromisoformat(abs_time).strftime("%H:%M:%S")
                except ValueError:
                    time_label = ""
            elif start_dt:
                time_label = start_dt.strftime("%H:%M:%S")
            else:
                time_label = ""
            text = (item.get("text") or "").strip()
            if text:
                rows.append(ControlCenterRow(time=time_label, text=text))
    return rows


def title_date_from_results(
    all_results: list[dict],
    filename_datetimes: dict[str, datetime] | None = None,
) -> str:
    """Return the first parsed recording date as YYYYMMDD for the document title."""
    filename_datetimes = filename_datetimes or {}
    dts = list(filename_datetimes.values())
    for result in all_results:
        stem = Path(result.get("filename", "")).stem
        dt = filename_datetimes.get(stem) or parse_filename_datetime(stem)
        if dt:
            dts.append(dt)
    if not dts:
        return datetime.now().strftime("%Y%m%d")
    return min(dts).strftime("%Y%m%d")


def export_control_center_docx(
    all_results: list[dict],
    filename_datetimes: dict[str, datetime] | None,
    output_dir: Path,
    *,
    timestamp: str,
    event_name: str = "",
) -> Path:
    """Write the DOCX export and return its path."""
    title = title_date_from_results(all_results, filename_datetimes)
    rows = collect_control_center_rows(all_results, filename_datetimes)
    safe_event = _safe_filename(event_name.strip()) if event_name else ""
    prefix = f"{safe_event}_" if safe_event else ""
    out_path = output_dir / f"{prefix}行控中心格式_{title}_{timestamp}.docx"
    write_control_center_docx(out_path, title, rows)
    return out_path


def _parse_db_datetime(value: str | None) -> datetime | None:
    """Parse a SQLite datetime string (``CURRENT_TIMESTAMP`` is UTC)."""
    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _rows_and_title_from_records(
    records: list[dict],
    *,
    utc_to_local: bool = True,
) -> tuple[str, list[ControlCenterRow]]:
    """Build (title, rows) from realtime transcript records.

    Each record is ``{"transcript": str, "created_at": "YYYY-MM-DD HH:MM:SS"}``
    (one committed sentence per record).  ``created_at`` from SQLite
    ``CURRENT_TIMESTAMP`` is UTC; with ``utc_to_local`` it is shifted to the
    server local timezone so the table shows the realtime receipt wall-clock
    time.  Rows are sorted ascending by time; one row per record.
    """
    local_tz = datetime.now().astimezone().tzinfo if utc_to_local else None
    parsed: list[tuple[datetime | None, str]] = []
    for rec in records:
        text = (rec.get("transcript") or "").strip()
        if not text:
            continue
        dt = _parse_db_datetime(rec.get("created_at"))
        if dt is not None and local_tz is not None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone(local_tz).replace(tzinfo=None)
        parsed.append((dt, text))

    parsed.sort(key=lambda item: item[0] or datetime.max)
    rows = [
        ControlCenterRow(time=(dt.strftime("%H:%M:%S") if dt else ""), text=text)
        for dt, text in parsed
    ]
    dated = [dt for dt, _ in parsed if dt is not None]
    title = (min(dated) if dated else datetime.now()).strftime("%Y%m%d")
    return title, rows


def export_control_center_from_records(
    records: list[dict],
    output_dir: Path,
    *,
    timestamp: str,
    event_name: str = "",
    fmt: str = "docx",
    utc_to_local: bool = True,
) -> Path:
    """Export realtime transcript records to a control-center file.

    ``fmt`` is one of ``"docx"`` (default), ``"pdf"`` (rendered from the DOCX via
    LibreOffice) or ``"txt"`` (tab-separated table).  Returns the output path.
    """
    fmt = (fmt or "docx").lower()
    title, rows = _rows_and_title_from_records(records, utc_to_local=utc_to_local)
    safe_event = _safe_filename(event_name.strip()) if event_name else ""
    prefix = f"{safe_event}_" if safe_event else ""
    stem = f"{prefix}行控中心格式_{title}_{timestamp}"

    if fmt == "txt":
        out_path = output_dir / f"{stem}.txt"
        write_control_center_txt(out_path, title, rows)
        return out_path
    if fmt == "pdf":
        docx_path = output_dir / f"{stem}.docx"
        write_control_center_docx(docx_path, title, rows)
        return _docx_to_pdf(docx_path)

    out_path = output_dir / f"{stem}.docx"
    write_control_center_docx(out_path, title, rows)
    return out_path


def write_control_center_txt(path: Path, title: str, rows: list[ControlCenterRow]) -> None:
    """Write the control-center transcript table as a tab-separated text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [title, "運務處行控中心", "", "時間\t發話者\t通聯內容\t備註"]
    if rows:
        lines.extend(f"{r.time}\t{r.speaker}\t{r.text}\t{r.note}" for r in rows)
    else:
        lines.append("\t\t（無辨識結果）\t")
    path.write_text("\n".join(lines), encoding="utf-8")


def _find_soffice() -> str | None:
    """Locate the LibreOffice headless binary, if installed."""
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found
    for path in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",):
        if Path(path).exists():
            return path
    return None


def _docx_to_pdf(docx_path: Path) -> Path:
    """Render a DOCX to PDF via LibreOffice headless (preserves the table layout)."""
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            "找不到 LibreOffice（soffice），無法產生 PDF；請改用 Word/txt 或安裝 LibreOffice。"
        )
    # 獨立 UserInstallation profile：避免與既有 soffice 實例衝突而轉檔失敗
    with tempfile.TemporaryDirectory() as profile:
        proc = subprocess.run(
            [
                soffice, "--headless", "--norestore",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RuntimeError(
            f"docx→pdf 轉檔失敗：{(proc.stderr or proc.stdout or '未知錯誤').strip()}"
        )
    return pdf_path


def write_control_center_docx(path: Path, title: str, rows: list[ControlCenterRow]) -> None:
    """Create a Word-compatible DOCX with the control-center transcript table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document_xml = _document_xml(title, rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("docProps/core.xml", _core_xml(title))
        zf.writestr("docProps/app.xml", _app_xml())
        zf.writestr("word/document.xml", document_xml)


def _safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", value).strip("_")[:40]


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""


def _root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _core_xml(title: str) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    esc_title = escape(title)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{esc_title}</dc:title>
  <dc:creator>aiSpeechMulti</dc:creator>
  <cp:lastModifiedBy>aiSpeechMulti</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>"""


def _app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>aiSpeechMulti</Application>
</Properties>"""


def _document_xml(title: str, rows: list[ControlCenterRow]) -> str:
    table_rows = [_table_row(["時間", "發話者", "通聯內容", "備註"], header=True)]
    if rows:
        table_rows.extend(_table_row([r.time, r.speaker, r.text, r.note]) for r in rows)
    else:
        table_rows.append(_table_row(["", "", "（無辨識結果）", ""]))

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {_paragraph(title, align="center", bold=True, size=36)}
    {_paragraph("運務處行控中心", align="right", size=24)}
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="10348" w:type="dxa"/>
        <w:tblLayout w:type="fixed"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>
          <w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>
          <w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>
          <w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>
          <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>
          <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>
        </w:tblBorders>
      </w:tblPr>
      <w:tblGrid>
        <w:gridCol w:w="1701"/>
        <w:gridCol w:w="1985"/>
        <w:gridCol w:w="5528"/>
        <w:gridCol w:w="1134"/>
      </w:tblGrid>
      {''.join(table_rows)}
    </w:tbl>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="851" w:footer="992" w:gutter="0"/>
      <w:cols w:space="425"/>
      <w:docGrid w:type="lines" w:linePitch="360"/>
    </w:sectPr>
  </w:body>
</w:document>"""


def _table_row(values: list[str], header: bool = False) -> str:
    widths = [1701, 1985, 5528, 1134]
    aligns = ["center", "center", "both", "center"]
    cells = [
        _table_cell(value, width, align, header=header)
        for value, width, align in zip(values, widths, aligns)
    ]
    header_prop = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return f"<w:tr>{header_prop}{''.join(cells)}</w:tr>"


def _table_cell(value: str, width: int, align: str, *, header: bool = False) -> str:
    shading = '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>' if header else ""
    return f"""<w:tc>
  <w:tcPr>
    <w:tcW w:w="{width}" w:type="dxa"/>
    <w:vAlign w:val="center"/>
    <w:tcMar>
      <w:top w:w="80" w:type="dxa"/>
      <w:left w:w="80" w:type="dxa"/>
      <w:bottom w:w="80" w:type="dxa"/>
      <w:right w:w="80" w:type="dxa"/>
    </w:tcMar>
    {shading}
  </w:tcPr>
  {_paragraph(value, align=align, bold=header, size=28)}
</w:tc>"""


def _paragraph(value: str, *, align: str = "left", bold: bool = False, size: int = 28) -> str:
    bold_xml = "<w:b/>" if bold else ""
    text = escape(value or "")
    return f"""<w:p>
  <w:pPr>
    <w:widowControl/>
    <w:spacing w:line="500" w:lineRule="exact"/>
    <w:jc w:val="{align}"/>
    <w:rPr>{_font_xml()}{bold_xml}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>
  </w:pPr>
  <w:r>
    <w:rPr>{_font_xml()}{bold_xml}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>
    <w:t>{text}</w:t>
  </w:r>
</w:p>"""


def _font_xml() -> str:
    return '<w:rFonts w:ascii="Times New Roman" w:eastAsia="標楷體" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
