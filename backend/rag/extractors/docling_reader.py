"""Docling (open-source models only, all local): page layout, tables (TableFormer) and OCR for scanned pages
and images. Text-layer PDF pages are still read directly with PyMuPDF (pdf.py), which is far faster."""
import logging
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from .base import Segment, clean_cell, table_from_grid

log = logging.getLogger("rag.docling")
_lock = threading.Lock()  # one conversion at a time: the models are large and share the CPU

SKIP = {"page_footer", "picture", "chart"}  # footers repeat page numbers; figures carry no text here (scanned titles are often "page_header", so those are kept)
HEADINGS = {"title", "section_header"}


@lru_cache
def converter():
    """Built once per process; loads the layout, table and OCR models (downloaded on first use)."""
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (EasyOcrOptions, PdfPipelineOptions, RapidOcrOptions,
                                                    TableFormerMode, TesseractCliOcrOptions)
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    s = get_settings()
    langs = [x.strip() for x in s.docling_lang.split(",") if x.strip()]
    if s.docling_ocr == "rapidocr":
        ocr = RapidOcrOptions()
    elif s.docling_ocr == "tesseract":
        ocr = TesseractCliOcrOptions(lang=[{"en": "eng", "hi": "hin"}.get(x, x) for x in langs])
    else:
        ocr = EasyOcrOptions(lang=langs)
    options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr,
        do_table_structure=True,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.AUTO, num_threads=os.cpu_count() or 4),
    )
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
    })


def read(path: Path, page_numbers: list[int] | None = None) -> dict[int, list[Segment]]:
    """Segments per page (1-based). `page_numbers` maps the file's pages back to the original document
    (when `path` holds only some pages of it)."""
    from docling_core.types.doc import TableItem, TextItem

    with _lock:
        result = converter().convert(str(path), raises_on_error=True)
    doc = result.document
    pages: dict[int, list[Segment]] = {}
    headings: list[str] = []

    for item, level in doc.iterate_items():
        prov = getattr(item, "prov", None)
        page_no = prov[0].page_no if prov else 1
        page = page_numbers[page_no - 1] if page_numbers and page_no <= len(page_numbers) else page_no
        label = str(getattr(item, "label", "")).split(".")[-1].lower()
        if label in SKIP:
            continue
        loc = {"page": page, **({"section": " > ".join(headings)} if headings else {})}

        if isinstance(item, TableItem):
            grid = _table_grid(item, doc)
            preamble, header, rows = table_from_grid(grid)
            if preamble:
                pages.setdefault(page, []).append(Segment("text", loc, text=preamble, ocr=True))
            if header or rows:
                pages.setdefault(page, []).append(Segment("table", loc, header=header, rows=rows, ocr=True))
        elif isinstance(item, TextItem):
            text = (item.text or "").strip()
            if not text or looks_like_noise(text):
                continue
            if label in HEADINGS:
                depth = max(1, min(level, 6)) if label == "section_header" else 1
                headings[:] = headings[: depth - 1] + [text[:120]]
                loc = {"page": page, "section": " > ".join(headings)}
            pages.setdefault(page, []).append(Segment("text", loc, text=text, ocr=True))
    return pages


_WORD = re.compile(r"^[A-Za-z][a-z]+[.,:;)]?$|^[A-Z]{2,}[.,:;)]?$|^[(\d][\d.,:/()-]*$|^[^\W\d_]{2,}$")


def looks_like_noise(text: str) -> bool:
    """OCR of stamps, signatures or upside-down text: mostly tokens that are not words or numbers,
    e.g. '*O66T=OT-6T £30\' "WHETP ION SW*O"'. Short blocks are kept (dates, names, page numbers)."""
    tokens = text.split()
    if len(tokens) < 6:
        return False
    return sum(bool(_WORD.match(t)) for t in tokens) / len(tokens) < 0.45


def _table_grid(item, doc) -> list[list[str]]:
    df = item.export_to_dataframe(doc=doc)
    header = [clean_cell(c) for c in df.columns]
    rows = [[clean_cell(v) for v in row] for row in df.astype(str).values.tolist()]
    numbered = all(h.isdigit() for h in header)  # no real header row detected: columns are 0, 1, 2…
    return rows if numbered else [header] + rows
