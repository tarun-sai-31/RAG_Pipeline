"""Type detection and routing. Every file type ends up as an Extraction (a list of Segments)."""
import logging
import tempfile
import zipfile
from pathlib import Path

from ..config import get_settings
from .base import Extraction, Segment, UnsupportedFile
from .ocr import image_to_png, ocr_image_bytes
from .office import extract_csv, extract_docx, extract_xlsx, soffice_convert
from .pdf import extract_pdf

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
TEXT_EXT = {".txt", ".md", ".log", ".json", ".xml", ".yaml", ".yml", ".ini",
            ".js", ".ts", ".py", ".css", ".sql", ".sh"}
HTML_EXT = {".html", ".htm"}
# LibreOffice converts these first: (target extension, extractor of the converted file)
CONVERT = {
    ".doc": "docx", ".rtf": "docx", ".odt": "docx", ".wpd": "docx",
    ".xls": "xlsx", ".xlsb": "xlsx", ".ods": "xlsx", ".xlsm": "xlsx",
    ".ppt": "pdf", ".pptx": "pdf", ".odp": "pdf",
}


def detect_type(path: Path, filename: str) -> str:
    """File type from content first (renamed files are common), then from the extension."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    ext = Path(filename).suffix.lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            names = set()
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "xl/workbook.bin" in names:
            return "xlsb"
        if "ppt/presentation.xml" in names:
            return "pptx"
    if head[:4] in (b"\x89PNG", b"GIF8") or head[:3] == b"\xff\xd8\xff" or head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image"
    if ext in IMAGE_EXT:
        return "image"
    return ext.lstrip(".") or "unknown"


def extract(path: Path, file_type: str) -> Extraction:
    ext = f".{file_type}"
    if file_type == "pdf":
        return extract_pdf(path)
    if file_type == "docx":
        return extract_docx(path)
    if file_type == "xlsx":
        return extract_xlsx(path)
    if file_type == "csv":
        return extract_csv(path)
    if file_type == "image":
        if get_settings().ocr_engine == "docling":
            try:
                from . import docling_reader
                found = docling_reader.read(path)
                segs = [seg for n in sorted(found) for seg in found[n]]
                if sum(len(x.text) for x in segs) + sum(len(r) for x in segs for r in x.rows) >= 20:
                    return Extraction(segs, page_count=max(found, default=1), ocr_page_count=max(found, default=1))
                # Docling saw only a picture (photo, drawing): fall through to plain full-page OCR below

            except Exception:
                logging.getLogger("rag.extract").exception("Docling failed on %s; using Tesseract", path.name)
        pages = image_to_png(path.read_bytes())
        segs = [Segment("text", {"page": i + 1}, text=t, ocr=True)
                for i, t in enumerate(ocr_image_bytes(p) for p in pages) if t]
        return Extraction(segs, page_count=len(pages), ocr_page_count=len(pages))
    if ext in TEXT_EXT:
        return Extraction([Segment("text", {}, text=path.read_text(errors="replace"))])
    if ext in HTML_EXT:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(path.read_bytes(), "lxml").get_text("\n", strip=True)
        return Extraction([Segment("text", {}, text=text)])
    target = CONVERT.get(ext)
    if target is None:
        raise UnsupportedFile(f"Unsupported file type: {file_type}")
    with tempfile.TemporaryDirectory() as tmp:
        # LibreOffice picks the input filter by extension, so give the copy the right one.
        src = Path(tmp) / f"input{ext}"
        src.symlink_to(path.resolve())
        converted = soffice_convert(src, target, Path(tmp))
        return extract(converted, target)
