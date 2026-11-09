"""Word, Excel, CSV, and LibreOffice conversion for legacy/other office formats."""
import csv
import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

import docx
import openpyxl
from docx.table import Table
from docx.text.paragraph import Paragraph

from .base import Extraction, Segment, clean_cell, table_from_grid

MAX_SHEET_ROWS = 50_000


def soffice_convert(path: Path, target_ext: str, out_dir: Path) -> Path:
    """Convert with headless LibreOffice using a throwaway profile, so parallel workers don't collide."""
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
             "--convert-to", target_ext, "--outdir", str(out_dir), str(path)],
            check=True, capture_output=True, timeout=600,
        )
    produced = out_dir / f"{path.stem}.{target_ext}"
    if not produced.exists():
        raise RuntimeError(f"LibreOffice did not produce a .{target_ext} for {path.name}")
    return produced


# ---------- Word ----------

def _heading_level(p: Paragraph) -> int | None:
    name = (p.style.name if p.style is not None else "") or ""
    if name.lower() == "title":
        return 1
    if name.lower().startswith("heading"):
        digits = "".join(ch for ch in name if ch.isdigit())
        return int(digits) if digits else 1
    return None


def _docx_table_grid(table: Table) -> list[list[str]]:
    grid = []
    for row in table.rows:
        cells, last = [], None
        for cell in row.cells:
            # Horizontally merged cells repeat the same cell object; keep it once.
            if cell._tc is last:
                continue
            last = cell._tc
            cells.append(clean_cell(cell.text))
        grid.append(cells)
    return grid


def extract_docx(path: Path) -> Extraction:
    document = docx.Document(str(path))
    segments: list[Segment] = []
    headings: list[str] = []
    buffer: list[str] = []

    def section_loc() -> dict:
        return {"section": " > ".join(headings)} if headings else {}

    def flush():
        if buffer:
            segments.append(Segment("text", section_loc(), text="\n".join(buffer)))
            buffer.clear()

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block)
            if level:
                flush()
                headings[:] = headings[: level - 1] + [text[:120]]
            buffer.append(text)
        elif isinstance(block, Table):
            flush()
            preamble, header, rows = table_from_grid(_docx_table_grid(block))
            if preamble:
                segments.append(Segment("text", section_loc(), text=preamble))
            if header or rows:
                segments.append(Segment("table", section_loc(), header=header, rows=rows))
    flush()

    for section in document.sections:  # headers often carry the project name and report date
        for part in (section.header, section.footer):
            text = "\n".join(p.text.strip() for p in part.paragraphs if p.text.strip())
            if text and not any(s.text == text for s in segments):
                segments.insert(0, Segment("text", {"section": "Header/Footer"}, text=text))
    return Extraction(segments)


# ---------- Excel / CSV ----------

def _without_empty_defined_names(path: Path) -> io.BytesIO:
    """LibreOffice-converted workbooks can contain empty <definedName> print titles that openpyxl rejects."""
    out = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/workbook.xml":
                data = re.sub(rb"<definedName[^>]*/>|<definedName[^>]*>\s*</definedName>", b"", data)
            zout.writestr(item, data)
    out.seek(0)
    return out


def extract_xlsx(path: Path) -> Extraction:
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except TypeError:
        wb = openpyxl.load_workbook(_without_empty_defined_names(path), read_only=True, data_only=True)
    segments: list[Segment] = []
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            grid = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_SHEET_ROWS:
                    break
                grid.append([clean_cell(v) for v in row])
            segments.extend(_grid_segments(grid, {"sheet": ws.title}))
    finally:
        wb.close()
    return Extraction(segments, page_count=len(wb.sheetnames))


def extract_csv(path: Path) -> Extraction:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:5000])
    except csv.Error:
        dialect = csv.excel
    grid = [[clean_cell(c) for c in row] for row in csv.reader(text.splitlines(), dialect)]
    return Extraction(_grid_segments(grid[:MAX_SHEET_ROWS], {}))


def _grid_segments(grid: list[list[str]], loc: dict) -> list[Segment]:
    preamble, header, rows = table_from_grid(grid)
    out = []
    if preamble:
        out.append(Segment("text", loc, text=preamble))
    if header or rows:
        out.append(Segment("table", loc, header=header, rows=rows))
    return out
