"""PDF: decide per page. Pages with a real text layer are read directly (milliseconds); scanned or
image-only pages go to Docling (layout + tables + OCR), or to Tesseract/Gemini if OCR_ENGINE says so.
Mixed PDFs work because the choice is per page."""
import logging
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import fitz  # PyMuPDF

from ..config import get_settings
from .base import Extraction, Segment, clean_cell, table_from_grid
from .ocr import ocr_image_bytes

log = logging.getLogger("rag.pdf")
MAX_RENDER_PX = 5000  # large drawings (A0 maps) would otherwise render at 14,000+ px


def _real_chars(text: str) -> int:
    return sum(ch.isalnum() for ch in text)


def needs_ocr(page: fitz.Page, min_chars: int) -> bool:
    text = page.get_text("text")
    real = _real_chars(text)
    if real >= min_chars:
        # A text layer of broken glyphs (missing font maps) is as good as none.
        junk = sum(1 for ch in text if ch == "�" or 0xE000 <= ord(ch) <= 0xF8FF)
        return junk > 0.3 * max(real, 1)
    # Little text: OCR only if there is something to read (a scan image or vector-drawn text).
    return bool(page.get_images()) or len(page.get_cdrawings()) > 50


def _render_png(page: fitz.Page, dpi: int) -> bytes:
    zoom = dpi / 72
    longest = max(page.rect.width, page.rect.height) * zoom
    if longest > MAX_RENDER_PX:
        zoom *= MAX_RENDER_PX / longest
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY).tobytes("png")


def _ocr_page(args: tuple[str, int], engine: str | None = None) -> str:
    path, page_no = args
    settings = get_settings()
    with fitz.open(path) as doc:
        png = _render_png(doc[page_no], settings.ocr_dpi)
    return ocr_image_bytes(png, engine=engine)


def _text_page(page: fitz.Page) -> list[Segment]:
    """Tables become table segments; text blocks outside them become prose, all in top-to-bottom order."""
    items: list[tuple[float, Segment]] = []
    boxes = []
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    loc = {"page": page.number + 1}
    for t in tables:
        grid = [[clean_cell(c) for c in row] for row in t.extract()]
        preamble, header, rows = table_from_grid(grid)
        if not rows and not header:
            continue
        boxes.append(fitz.Rect(t.bbox))
        if preamble:
            items.append((t.bbox[1] - 0.1, Segment("text", loc, text=preamble)))
        items.append((t.bbox[1], Segment("table", loc, header=header, rows=rows)))
    for x0, y0, x1, y1, text, _no, kind in page.get_text("blocks", sort=True):
        if kind != 0 or not text.strip():
            continue
        centre = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if any(centre in b for b in boxes):
            continue
        items.append((y0, Segment("text", loc, text=text.strip())))
    items.sort(key=lambda it: it[0])
    return [seg for _, seg in items]


def _docling_pages(path: Path, pages: list[int]) -> dict[int, list[Segment]]:
    """Run Docling on just the scanned pages (copied into a temporary PDF), keyed by 0-based page index."""
    from . import docling_reader

    with tempfile.TemporaryDirectory() as tmp, fitz.open(path) as doc:
        subset = Path(tmp) / "scanned.pdf"
        doc.select(pages)
        doc.save(subset)
        found = docling_reader.read(subset, page_numbers=[n + 1 for n in pages])
    result = {n: found.get(n + 1, []) for n in pages}
    # Docling's layout model can treat a whole page as a picture (maps, drawings, photos of documents) and then
    # reads no text from it. Re-read such pages with plain full-page Tesseract so their text is not lost.
    min_chars = get_settings().min_text_chars
    for n, segs in result.items():
        if sum(_real_chars(x.text) + sum(_real_chars(c) for r in x.rows for c in r) for x in segs) < min_chars:
            text = _ocr_page((str(path), n), engine="tesseract")
            if text:
                log.info("%s page %d: Docling found no text; used Tesseract", path.name, n + 1)
                result[n] = [Segment("text", {"page": n + 1}, text=text, ocr=True)]
    return result


def extract_pdf(path: Path) -> Extraction:
    settings = get_settings()
    per_page: dict[int, list[Segment]] = {}
    to_ocr: list[int] = []
    with fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF is password protected")
        page_count = doc.page_count
        for page in doc:
            if needs_ocr(page, settings.min_text_chars):
                to_ocr.append(page.number)
            else:
                per_page[page.number] = _text_page(page)

    if to_ocr and settings.ocr_engine == "docling":
        try:
            per_page.update(_docling_pages(path, to_ocr))
            to_ocr_done = True
        except Exception:
            log.exception("Docling failed on %s; falling back to Tesseract", path.name)
            to_ocr_done = False
    else:
        to_ocr_done = False

    if to_ocr and not to_ocr_done:
        jobs = [(str(path), n) for n in to_ocr]
        if len(jobs) == 1 or settings.ocr_workers <= 1:
            texts = [_ocr_page(j) for j in jobs]
        else:
            with ProcessPoolExecutor(max_workers=min(settings.ocr_workers, len(jobs))) as pool:
                texts = list(pool.map(_ocr_page, jobs))
        for n, text in zip(to_ocr, texts):
            per_page[n] = [Segment("text", {"page": n + 1}, text=text, ocr=True)] if text else []

    segments = [seg for n in sorted(per_page) for seg in per_page[n]]
    return Extraction(segments, page_count=page_count, ocr_page_count=len(to_ocr))
