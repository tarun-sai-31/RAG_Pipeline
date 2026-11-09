"""OCR for scanned pages and images. Tesseract runs locally for free; Gemini reads tables and poor scans better."""
import io

from PIL import Image

from ..config import get_settings

GEMINI_OCR_PROMPT = (
    "Transcribe all text in this scanned page exactly as written, in reading order. "
    "Write tables as Markdown tables. Do not summarise, translate or add commentary. "
    "If there is no text, reply with nothing."
)


def ocr_image_bytes(png: bytes, engine: str | None = None) -> str:
    """Plain full-page OCR (Docling is handled in docling_reader). Gemini only when chosen in OCR_ENGINE."""
    if (engine or get_settings().ocr_engine) == "gemini":
        return _gemini(png)
    return _tesseract(png)


def _tesseract(png: bytes) -> str:
    import pytesseract

    settings = get_settings()
    with Image.open(io.BytesIO(png)) as img:
        return pytesseract.image_to_string(img, lang=settings.ocr_lang, config="--psm 3").strip()


def _gemini(png: bytes) -> str:
    from google.genai import types

    from ..gemini import _with_retry, client

    settings = get_settings()
    resp = _with_retry(lambda: client().models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), GEMINI_OCR_PROMPT],
        config=types.GenerateContentConfig(temperature=0),
    ), model=settings.gemini_model, quota_wait=settings.quota_wait_minutes * 60)
    return (resp.text or "").strip()


def image_to_png(data: bytes, max_px: int = 4000) -> list[bytes]:
    """Normalise any image (including multi-page TIFF) to PNG pages for OCR."""
    pages = []
    with Image.open(io.BytesIO(data)) as img:
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            frame = img.convert("RGB")
            frame.thumbnail((max_px, max_px))
            buf = io.BytesIO()
            frame.save(buf, "PNG")
            pages.append(buf.getvalue())
    return pages
